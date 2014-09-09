#!/usr/bin/env python
'''
Cross-platform getch class.
References:
    http://stackoverflow.com/questions/510357/python-read-a-single-character-from-the-user
    http://www.darkcoding.net/software/non-blocking-console-io-is-not-possible/
Note:
    Might be able to better use https://pypi.python.org/pypi/getch
    as an alternative.
    Unusure of Mac OS X and Windows Support
    (module recommends msvcrt on Windows)
'''


def is_data(timeout=1):
    '''
    Checks to see if there is data ready to read on stdin.
    '''
    import sys
    import select

    rdy = select.select([sys.stdin], [], [], timeout) == ([sys.stdin], [], [])
    return rdy


class _Getch(object):
    '''
    Gets a single character from standard input.  Does not echo to the
    screen.
    '''
    def __init__(self, timeout=1):
        '''
        Figure out which class to actually be for _Getch.
        '''
        self.timeout = timeout
        try:
            self.impl = _GetchWindows(self.timeout)
        except ImportError:
            try:
                self.impl = _GetchUnix(self.timeout)
            except ImportError:
                self.impl = _GetchMacCarbon(self.timeout)

    def __call__(self):
        '''
        Grab from the imports
        '''
        return self.impl()


class _GetchUnix(object):
    '''
    Unix version of _Getch
    '''
    def __init__(self, timeout):
        '''
        Imports to make sure we can run
        '''
        # import termios now or else you'll get the Unix version on the Mac
        import tty
        import sys
        import termios
        self.timeout = timeout

    def __call__(self):
        '''
        Get our character
        '''
        # select to prevent blocking
        import sys
        import tty
        import termios

        fd = sys.stdin
        old_settings = termios.tcgetattr(fd)
        ch = None
        try:
            tty.setcbreak(sys.stdin.fileno())
            if is_data(self.timeout):
                ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        return ch


class _GetchWindows(object):
    '''
    Windows Version of _Getch
    Just pass msvcrt.getch() back
    '''
    def __init__(self, timeout):
        '''
        Import msvcrt to make sure we can load this class
        '''
        import msvcrt

        self.timeout = timeout

    def __call__(self):
        '''
        Just use msvcrt.getch()
        start_time is to emulate timeout used by unix
        '''
        import msvcrt
        import time
        start_time = time.time()
        while True:
            if msvcrt.kbhit():
                c = msvcrt.getch()
                break
            elif time.time() - start_time > self.timeout:
                c = None
                break
        return c


class _GetchMacCarbon(object):
    '''
    A function which returns the current ASCII key that is down;
    if no ASCII key is down, the null string is returned.  The
    page http://www.mactech.com/macintosh-c/chap02-1.html was
    very helpful in figuring out how to do this.
    '''
    def __init__(self, timeout):
        '''
        Import Carbon on init
        '''
        import Carbon

        self.timeout = timeout

    def __call__(self):
        '''
        Grab the character
        '''
        import Carbon
        import time
        start_time = time.time()
        event = Carbon.Event()
        while True:
            # 0x0008 is the keyDownMask
            if not event.EventAvail(0x0008)[0] == 0:
                #
                # The event contains the following info:
                # (what,msg,when,where,mod)=Carbon.Evt.GetNextEvent(0x0008)[1]
                #
                # The message (msg) contains the ASCII char which is
                # extracted with the 0x000000FF charCodeMask; this
                # number is converted to an ASCII character with chr() and
                # returned
                #
                (what, msg, when, where, mod) = event.GetNextEvent(0x0008)[1]
                c = chr(msg & 0x000000FF)
                break
            elif time.time() - start_time > self.timeout:
                c = None
                break
            return c

if __name__ == '__main__':
    char = _Getch()
    while True:
        character = char()
        if character:
            print character
        if character == '\x1b':
            break
