# -*- coding: utf-8 -
#
# This file is part of offset. See the NOTICE for more information.


__os_mod__ = __import__("os")
__select_mod__ = __import__("select")
__socket_mod__ = __import__("socket")
__selectors_mod__ = __import__("selectors")
_socket = __import__("socket")

import io
import wrapt
from ..core import syscall, enter_syscall

__all__ = ['OsProxy', 'SelectProxy']


# proxy the OS module

class OsProxy(wrapt.ObjectProxy):
    """ proxy the os module """

    _OS_SYSCALLS =  ("chown", "fchown", "close", "dup", "dup2", "read",
            "pread","write", "pwrite", "sendfile", "readv", "writev", "stat",
            "lstat", "truncate", "sync", "lseek", "open", "posix_fallocate",
            "posix_fadvise", "chmod", "chflags", )

    def __init__(self):
        super(OsProxy, self).__init__(__os_mod__)

    def __getattr__(self, name):
        # wrap syscalls
        if name in self._OS_SYSCALLS:
            return syscall(getattr(self.__wrapped__, name))
        return getattr(self.__wrapped__, name)


if hasattr(_socket, "SocketIO"):
    SocketIO = _socket.SocketIO
else:
    from _socketio import SocketIO

class socket(object):
    """A subclass of _socket.socket wrapping the makefile() method and
    patching blocking calls. """

    __slots__ = ('_io_refs', '_sock', '_closed', )

    _BL_SYSCALLS = ('accept', 'getpeername', 'getsockname',
            'getsockopt', 'ioctl', 'recv', 'recvfrom', 'recvmsg',
            'recvmsg_into', 'recvfrom_into', 'recv_into', 'send',
            'sendall', 'sendto', 'sendmsg', )

    def __init__(self, family=_socket.AF_INET, type=_socket.SOCK_STREAM,
            proto=0, fileno=None):

        if fileno is not None:
            if hasattr(_socket.socket, 'detach'):
                self._sock = _socket.socket(family, type, proto, fileno)
            else:
                self._sock = _socket.fromfd(fileno, family, type, proto)
        else:
            self._sock = _socket.socket(family, type, proto)

        self._io_refs = 0
        self._closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        if not self._closed:
            self.close()

    def __getattr__(self, name):
        # wrap syscalls
        if name in self._BL_SYSCALLS:
            return syscall(getattr(self._sock, name))

        return getattr(self._sock, name)


    def makefile(self, mode="r", buffering=None, encoding=None,
            errors=None, newline=None):
        """makefile(...) -> an I/O stream connected to the socket

        The arguments are as for io.open() after the filename,
        except the only mode characters supported are 'r', 'w' and 'b'.
        The semantics are similar too.  (XXX refactor to share code?)
        """
        for c in mode:
            if c not in {"r", "w", "b"}:
                raise ValueError("invalid mode %r (only r, w, b allowed)")
        writing = "w" in mode
        reading = "r" in mode or not writing
        assert reading or writing
        binary = "b" in mode
        rawmode = ""
        if reading:
            rawmode += "r"
        if writing:
            rawmode += "w"
        raw = SocketIO(self, rawmode)
        self._io_refs += 1
        if buffering is None:
            buffering = -1
        if buffering < 0:
            buffering = io.DEFAULT_BUFFER_SIZE
        if buffering == 0:
            if not binary:
                raise ValueError("unbuffered streams must be binary")
            return raw
        if reading and writing:
            buffer = io.BufferedRWPair(raw, raw, buffering)
        elif reading:
            buffer = io.BufferedReader(raw, buffering)
        else:
            assert writing
            buffer = io.BufferedWriter(raw, buffering)
        if binary:
            return buffer
        text = io.TextIOWrapper(buffer, encoding, errors, newline)
        text.mode = mode
        return text

    def _decref_socketios(self):
        if self._io_refs > 0:
            self._io_refs -= 1
        if self._closed:
            self._sock.close()

    def close(self):
        self._closed = True
        if self._io_refs <= 0:
            """
            # socket shutdown
            try:
                self._sock.shutdown(_socket.SHUT_RDWR)
            except:
                pass
            """

            self._sock.close()

    def detach(self):
        self._closed = True
        if hasattr(self._sock, 'detach'):
            return self._sock.detach()

        new_fd = os.dup(self._sock.fileno())
        self._sock.close()

        # python 2.7 has no detach method, fake it
        return new_fd


class SocketProxy(wrapt.ObjectProxy):

    def __init__(self):
        super(SocketProxy, self).__init__(__socket_mod__)

    def socket(self, *args, **kwargs):
        return socket(*args, **kwargs)


    def fromfd(self, fd, family, type, proto=0):
        return socket(family, type, fileno=fd)

    if hasattr(socket, "share"):
        def fromshare(self, info):
            return socket(0, 0, 0, info)

    if hasattr(_socket, "socketpair"):
        def socketpair(self, family=None, type=__socket_mod__.SOCK_STREAM,
                proto=0):

            if family is None:
                try:
                    family = self.__wrapped__.AF_UNIX
                except NameError:
                    family = self.__wrapped__.AF_INET
            a, b = self.__wrapped__.socketpair(family, type, proto)

            if hasattr(a, 'detach'):
                a = socket(family, type, proto, a.detach())
                b = socket(family, type, proto, b.detach())
            else:
                a = socket(family, type, proto, a.fileno())
                b = socket(family, type, proto, b.fileno())

            return a, b


# proxy the socket proxy


class _Poll(object):

    def register(self, *args):
        return self.p.register(*args)

    def modify(self, *args):
        return self.p.modify(*args)

    def unregister(self, *args):
        return self.p.unregister(*args)

    def poll(self, *args, **kwargs):
        return enter_syscall(self.p.poll, *args)



if hasattr(__select_mod__, "devpoll"):

    class devpoll(_Poll):

        def __init__(self):
            self.p = __select_mod__.devpoll()

if hasattr(__select_mod__, "epoll"):

    class epoll(_Poll):

        def __init__(self):
            self.p = __select_mod__.epoll()

        def close(self):
            return self.p.close()

        def fileno(self):
            return self.p.fileno()

        def fromfd(self, fd):
            return self.p.fromfd(fd)

if hasattr(__select_mod__, "poll"):

    class poll(_Poll):

        def __init__(self):
            self.p = __select_mod__.poll()

if hasattr(__select_mod__, "kqueue"):

    class kqueue(object):

        def __init__(self):
            self.kq = __select_mod__.kqueue()

        def fileno(self):
            return self.kq.fileno()

        def fromfd(self, fd):
            return self.kq.fromfd(fd)

        def close(self):
            return self.kq.close()

        def control(self, *args, **kwargs):
            return enter_syscall(self.kq.control, *args, **kwargs)



class SelectProxy(wrapt.ObjectProxy):

    def __init__(self):
        super(SelectProxy, self).__init__(__select_mod__)

    if hasattr(__select_mod__, "devpoll"):
        def devpoll(self):
            return devpoll()

    if hasattr(__select_mod__, "epoll"):
        def epoll(self):
            return epoll()

    if hasattr(__select_mod__, "poll"):
        def poll(self):
            return poll()

    if hasattr(__select_mod__, "kqueue"):
        def kqueue(self):
            return kqueue()

    def select(self, *args, **kwargs):
        return enter_syscall(self.__wrapped__.select, *args, **kwargs)



# proxy selecrors

class BaseSelector(object):

    def register(self, *args, **kwargs):
        return self.s.register(*args, **kwargs)

    def unregister(self, *args):
        return self.s.unregister(*args)

    def modify(self, *args, **kwargs):
        return self.s.modify(self, *args, **kwargs)

    def select(self, timeout=None):
        return enter_syscall(self.s.register, timeout)

    def close(self):
        self.s.close()

    def get_key(self, fileobj):
        return self.s.get_key(fileobj)

    def get_map(self):
        return self.s.get_map()


if hasattr(__selectors_mod__, 'SelectSelector'):

    class SelectSelector(BaseSelector):

        def __init__(self):
            self.s = __selectors_mod__.SelectSelector()


if hasattr(__selectors_mod__, 'PollSelector'):

    class PollSelector(BaseSelector):

        def __init__(self):
            self.s = __selectors_mod__.PollSelector()


if hasattr(__selectors_mod__, 'EpollSelector'):

    class EpollSelector(BaseSelector):

        def __init__(self):
            self.s = __selectors_mod__.EpollSelector()

        def fileno(self):
            return self.s.fileno()


if hasattr(__selectors_mod__, 'KqueueSelector'):

    class KqueueSelector(BaseSelector):

        def __init__(self):
            self.s = __selectors_mod__.KqueueSelector()

        def fileno(self):
            return self.s.fileno()


if 'KqueueSelector' in globals():
    DefaultSelector = KqueueSelector
elif 'EpollSelector' in globals():
    DefaultSelector = EpollSelector
elif 'PollSelector' in globals():
    DefaultSelector = PollSelector
else:
    DefaultSelector = SelectSelector


class SelectorsProxy(wrapt.ObjectProxy):

    def __init__(self):
        super(SelectorsProxy, self).__init__(__selectors_mod__)

    if hasattr(__selectors_mod__, 'SelectSelector'):

        def SelectSelector(self):
            return SelectSelector()


    if hasattr(__selectors_mod__, 'PollSelector'):

        def PollSelector(self):
            return PollSelector()


    if hasattr(__selectors_mod__, 'EpollSelector'):

        def EpollSelector(self):
            return EpollSelector()


    if hasattr(__selectors_mod__, 'KqueueSelector'):

        def KqueueSelector(self):
            return KqueueSelector()

    if 'KqueueSelector' in globals():
        DefaultSelector = KqueueSelector
    elif 'EpollSelector' in globals():
        DefaultSelector = EpollSelector
    elif 'PollSelector' in globals():
        DefaultSelector = PollSelector
    else:
        DefaultSelector = SelectSelector
