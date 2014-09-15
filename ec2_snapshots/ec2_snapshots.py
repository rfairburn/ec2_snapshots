#!/usr/bin/env python
# -*- coding: utf-8 -*-

'''
Written by Robert Fairburn
robert.fairburn@c2fo.com

http://www.c2fo.com
http://devop.ninja
https://github.com/rfairburn/ec2_snapshots

Generate a list of hosts in ec2, Take snapshost of them.  Clean up
old snapshots.

It expects the file .boto to exist in your home directory with contents
as follows:

[Credentials]
aws_access_key_id = <AWS_ACCESS_KEY_ID>
aws_secret_access_key = <AWS_SECRET_ACCESS_KEY>
'''

import boto.ec2
import os
import sys
import yaml
import time
import argparse
import threading
import calendar

from boto.exception import BotoClientError, BotoServerError, EC2ResponseError
from datetime import datetime, timedelta
from threading import Thread, Lock
from Queue import Queue, Empty
from getch import _Getch


class StoppableThread(Thread):
    '''
    Thread class with a stop() method. The thread itself has to check
    regularly for the stopped() condition.
    http://stackoverflow.com/questions/323972/is-there-any-way-to-kill-a-thread-in-python
    '''
    def __init__(self, *args, **kwargs):
        '''
        Pass init back to Thread and register stop event
        '''
        super(StoppableThread, self).__init__(*args, **kwargs)
        self._stop = threading.Event()

    def stop(self):
        '''
        Set stop on stop event
        '''
        self._stop.set()

    def stopped(self):
        '''
        Check if we are stopped
        '''
        return self._stop.isSet()


def kill_all_threads():
    '''
    Loop the global threads and tell each to stop.
    Join to block until they quit.
    '''
    print 'Bleeding out the queue'
    while not q.empty():
        try:
            q.get(False)
        except Empty:
            continue
        q.task_done()
    print 'Killing worker threads'
    # send the kill event without blocking
    for thread in threads:
        thread.stop()
    # block them all until they die
    # this may be better handled another way
    # but will work for now
    for thread in threads:
        thread.join()


def progress_bar(percent):
    '''
    Take percent and make a progress bar
    twenty characters wide
    '''
    complete = int(percent // 5)
    todo = int(20 - complete)
    bar_text = '[{0}{1}] {2}%'.format('#' * complete, '-' * todo, percent)
    return bar_text


def parse_args():
    '''
    Get arguments from the command like with argparse
    '''
    parser = argparse.ArgumentParser(
        description='Generate a list of hosts and generate/cleanup snapshots'
        )
    parser.add_argument(
        '--interactive', '-i',
        required=False,
        help='Interactive',
        action='store_true')
    parser.add_argument(
        '--days', '-d',
        required=False, type=int,
        help='Snapshot Keep Days',
        default='3')
    parser.add_argument(
        '--threads', '-t',
        required=False, type=int,
        help='Worker Threads',
        default='15')
    parser.add_argument(
        '--region', '-r',
        required=False, help='EC2 Region',
        default='us-west-2')
    args = parser.parse_args()
    return args


def generate_host_dict(instance, args):
    '''
    Generate the dictionary of hosts from Amazon EC2 that we do the rest of
    the work on.  Format should look like this:
    {
        hostname:
            {
                id: ec2 instance.id
                block_devices:
                    {
                        block_device_name: amazon_volume_id
                    }
                snapshot_keep_days: ec2 instance.tags['snapshot_keep_days']
            }

    }

    Also generate a dict used for progress bars that looks like this
    (very redundant):
    {
        hostname:
            {
                block_device_name (block_device_id): completed_percent
            }
    }
    '''
    instance_id = str(instance.id)
    if 'snapshot_keep_days' in instance.tags:
        snapshot_keep_days = int(
            instance.tags['snapshot_keep_days'])
    else:
        # Temporarily zero to test
        snapshot_keep_days = int(args.days)
    if 'Name' in instance.tags:
        hostname = str(instance.tags['Name'])
    else:
        hostname = instance_id
    block_device_mapping = instance.block_device_mapping
    block_devices = {}
    block_device_status = {}
    for block_device_name, block_device_type in block_device_mapping.items():
        # This seems terribly redundant, but we need a dict to use
        # and one for the current progress, so there we are.
        # Generate Block Devices for Queue
        block_devices.update(
            {str(block_device_name): str(block_device_type.volume_id)}
        )
        # Block devices for the status dict
        block_device_text = '{0} ({1})'.format(
            str(block_device_name),
            str(block_device_type.volume_id))
        block_device_status.update({block_device_text: int(0)})
    hosts.update({hostname: block_device_status})

    host = (
        {
            hostname:
                {
                    'id': instance_id,
                    'snapshot_keep_days': snapshot_keep_days,
                    'block_devices': block_devices
                }
        }
    )
    return host


def populate_queue(conn, args):
    '''
    Use generate_host_dict to make dictionary items to work on then populate
    the queue with them.

    Afterward get all snapshots who's expire dates are older than now.
    '''
    # Add all hosts in region to be backed up to queue
    print 'Populating queue with instances to snapshot...'
    reservations = conn.get_all_reservations()
    for reservation in reservations:
        instances = reservation.instances
        for instance in instances:
            if instance.state == 'running':
                host = generate_host_dict(instance, args)
                q.put(['create', host])
    # Add all expired snapshots to queue
    print 'Populating queue with snapshots to delete...'
    snapshots = conn.get_all_snapshots()
    for snapshot in snapshots:
        if 'expire_time_unix' in snapshot.tags.keys():
            # get now in unixtime
            now = calendar.timegm(datetime.utcnow().utctimetuple())
            if now > int(snapshot.tags['expire_time_unix']):
                print '{0} scheduled for deletion'.format(snapshot.description)
                q.put(['delete', snapshot])


def acquire_lock(fun, *args, **kwargs):
    '''
    Run lock and run the function so that we maintain thread
    safety on shared data.
    '''
    lock.acquire()
    try:
        return_info = fun(*args, **kwargs)
    finally:
        lock.release()
    return return_info


def make_gui_hosts(make_all=False):
    '''
    Take the hosts dict made in generate_hosts_dict and change the percent to
    pretty bars.  Optionally only show the in-progress hosts (make_all=False)

    Dict should look like this:
    {
        hostname:
            {
                bd_name (bd_id): [#####---------------] 25%
            }
    }

    '''
    gui_hosts = {}
    for host, block_devices in hosts.items():
        update_host = False
        gui_block_devices = {}
        for block_device, percent in block_devices.items():
            if (percent > 0 and percent < 100) or make_all:
                gui_block_devices.update({block_device: progress_bar(percent)})
                update_host = True
        if update_host:
            gui_hosts.update({host: gui_block_devices})
    return gui_hosts


def show_completed_count(action, length):
    '''
    Show which items returned successfully and are complete
    '''
    use_s = 's' if length is not 1 else ''
    if action == 'create':
        print 'Completed {0} host{1}'.format(length, use_s)
    elif action == 'delete':
        print 'Deleted {0} snapshot{1}'.format(length, use_s)


def draw_gui_hosts(make_all=False):
    '''
    Draw the output.  Use sys.stdout.write for formatting while threaded
    '''
    gui_hosts = make_gui_hosts(make_all)
    if gui_hosts:
        output = yaml.dump(dict(gui_hosts), default_flow_style=False)
    else:
        output = ''
    print output
    length = len(completed_list)
    show_completed_count('create', length)
    print 'Hosts: {0}'.format(', '.join(completed_list))
    print 'Failed Hosts: {0}'.format(', '.join(failed_list))
    length = len(deleted_list)
    show_completed_count('delete', length)
    print 'Deleted Snapshots: {0}'.format(','.join(deleted_list))
    print 'Failed Snapshot Deletions: {0}'.format(','.join(failed_delete_list))
    return gui_hosts


def interactive_watcher():
    '''
    Watcher for when we want to actively display the progress
    Auto draw gui hosts and whatnot.
    '''
    text = _Getch(timeout=1)
    character = None
    full = False
    # avoid race condition where threads have not spawned yet
    can_exit = False
    # Just us and the main thread means it is time to bail out
    while True:
        if threading.active_count() > 2:
            # Threads have spawned safe to exit
            can_exit = True
        if threading.active_count() <= 2 and can_exit:
            # exit out because they have now closed
            break
        character = text()
        os.system('cls' if sys.platform == 'win32' else 'clear')
        acquire_lock(draw_gui_hosts, make_all=full)
        print 'Press ESC to (q)uit or obtain (f)ull details.'
        if character == 'f':
            full = not full
        if character == 'q' or character == '\x1b':
            kill_all_threads()
            break
    print 'Exiting.'


def passive_watcher():
    '''
    Don't show progress bars.  Just output 'completed' when host complets
    '''
    print 'Non-interactive mode enabled.  You may still press ESC to (q)uit.'
    length = acquire_lock(len, completed_list)
    show_completed_count('create', length)
    delete_length = acquire_lock(len, deleted_list)
    show_completed_count('delete', delete_length)
    # avoid a race condition where threads have not spawned yet
    text = _Getch(timeout=1)
    character = None
    can_exit = False
    while True:
        character = text()
        if threading.active_count() > 2:
            can_exit = True
        old_length = length
        length = acquire_lock(len, completed_list)
        if old_length < length:
            show_completed_count('create', length)
        old_delete_length = delete_length
        delete_length = acquire_lock(len, deleted_list)
        if old_delete_length < delete_length:
            show_completed_count('delete', delete_length)
        # Stop if just the main thread and us.
        # queue.empty check misses some so do this.
        if threading.active_count() <= 2 and can_exit:
            break
        if character == 'q' or character == '\x1b':
            kill_all_threads()
            break


def create_snapshot(host, conn):
    '''
    This function does the heavy lifting.
    '''
    # Assume true unless issue
    success = True
    snapshots = []
    canupdate = False
    hostname, host_data = host.items()[0]
    # print hostname
    for block_device, volume_id in host_data['block_devices'].items():
        name = '{0} ({1}): {2}'.format(hostname, host_data['id'], volume_id)
        description = '{0} ({1})'.format(block_device, volume_id)
        try:
            snapshot = conn.create_snapshot(
                volume_id,
                description=description,
            )
            print 'Creating snapshot {0} named {1}'.format(
                str(snapshot.id), name)
            now = datetime.utcnow()
            expire_time = now + timedelta(
                days=host_data['snapshot_keep_days']
            )
            expire_time_unix = str(
                calendar.timegm(expire_time.utctimetuple())
            )
            expire_time_human = time.strftime(
                "%a, %d %b %Y %H:%M:%S +0000",
                expire_time.utctimetuple()
            )
            conn.create_tags(
                [snapshot.id],
                {
                    'Name': name,
                    'expire_time_unix': expire_time_unix,
                    'expire_time_human': expire_time_human,
                }
            )
            snapshots.extend([snapshot])
        except (BotoClientError, BotoServerError, EC2ResponseError):
            acquire_lock(failed_list.extend, [hostname])
            return
    while True:
        if threading.current_thread().stopped():
            break
        snapshots_complete = True
        block_device_status = {}
        for snapshot in snapshots:
            # snapshot = conn.get_all_snapshots([snapshot.id])[0]
            if canupdate:
                snapshot.update()
            else:
                canupdate = True
            percent_string = str(snapshot.progress)
            try:
                percent = int(percent_string[:-1])
            except ValueError:
                # show at least 1% to populate progress bars
                percent = 1
            if snapshot.status == 'pending':
                snapshots_complete = False
            elif snapshot.status == 'error':
                success = False
            bd_text = str(snapshot.description)
            block_device_status.update({bd_text: percent})
        status = {hostname: block_device_status}
        acquire_lock(hosts.update, status)
        if snapshots_complete:
            if success:
                acquire_lock(completed_list.extend, [hostname])
                break
            else:
                acquire_lock(failed_list.extend, [hostname])
                break
        time.sleep(30)


def delete_snapshot(snapshot):
    '''
    Delete a snapshot
    '''
    # This is a pretty short-running function, but if the event says we should
    # be stopped, then don't run
    if threading.current_thread().stopped():
        return False
    # Obtain information for logging
    if 'Name' in snapshot.tags.keys():
        name = str(snapshot.tags['Name'])
    else:
        name = str(snapshot.description)
    # Delete the snapshot
    deleted = snapshot.delete()
    if deleted:
        acquire_lock(deleted_list.extend, [name])
    else:
        acquire_lock(failed_delete_list.extend, [name])
    # Throttle to keep from hammering api
    time.sleep(30)
    return deleted


def worker(conn):
    '''
    Worker thread. Does 3 things:
        1. Grab an item from the queue.
        2. Send it through the correct processor.
        3. Update queue status.
    '''
    while not (q.empty() or threading.current_thread().stopped()):
        item = q.get()
        if item[0] == 'create':
            create_snapshot(item[1], conn)
        elif item[0] == 'delete':
            delete_snapshot(item[1])
        q.task_done()


def main():
    '''
    Main thread.  Adds shared memory globals and spawns the other threads.
    '''
    global q
    q = Queue()
    global hosts
    hosts = dict()
    global lock
    lock = Lock()
    global completed_list
    completed_list = []
    global failed_list
    failed_list = []
    global threads
    threads = []
    global deleted_list
    deleted_list = []
    global failed_delete_list
    failed_delete_list = []
    args = parse_args()
    conn = boto.ec2.connect_to_region(args.region)
    populate_queue(conn, args)
    print 'Initial Queue Size {0}'.format(int(q.qsize()))
    if args.interactive:
        watcher = Thread(target=interactive_watcher)
    else:
        watcher = Thread(target=passive_watcher)
    watcher.daemon = False
    watcher.start()
    num_worker_threads = args.threads
    for _ in range(num_worker_threads):
        thread = StoppableThread(target=worker, args=(conn,))
        thread.daemon = False
        thread.start()
        threads.extend([thread])
    q.join()
    watcher.join()
    acquire_lock(draw_gui_hosts, make_all=True)

if __name__ == '__main__':
    sys.exit(main())
