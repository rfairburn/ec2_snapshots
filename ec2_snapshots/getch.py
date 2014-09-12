#!/usr/bin/env python
'''
Cross-platform getch class.
References:
    http://stackoverflow.com/questions/510357/python-read-a-single-character-from-the-user
    http://www.darkcoding.net/software/non-blocking-console-io-is-not-possible/
Note:
    Might be able to better use https://pypi.python.org/pypi/getch
    as an alternative.
    Unusure of  Windows Support
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
            self.impl = _GetchUnix(self.timeout)

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
        import time

        # Don't barf if we are not a tty, Just return nothing
        # because we won't expect a character anyhow
        if not sys.stdout.isatty():
            time.sleep(self.timeout)
            return None
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


if __name__ == '__main__':
    char = _Getch()
    while True:
        character = char()
        if character:
            print character
        if character == '\x1b':
            break
