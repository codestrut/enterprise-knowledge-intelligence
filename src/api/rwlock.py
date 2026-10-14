"""Writer-preferring read/write lock for the in-memory knowledge base.

Queries only read the indexes, so they can run concurrently. Indexing and
deleting mutate them (FAISS add, BM25 rebuild, chunk list replacement), so
those need exclusive access. The lock is deliberately not re-entrant: do not
acquire it again while already holding it.
"""

import threading
from contextlib import contextmanager


class ReadWriteLock:
    """Many concurrent readers or one writer; waiting writers go first."""

    def __init__(self):
        self._condition = threading.Condition()
        self._readers = 0
        self._writer_active = False
        self._writers_waiting = 0

    @contextmanager
    def read_lock(self):
        with self._condition:
            # A waiting writer blocks new readers so writers cannot starve.
            while self._writer_active or self._writers_waiting:
                self._condition.wait()
            self._readers += 1

        try:
            yield
        finally:
            with self._condition:
                self._readers -= 1
                if self._readers == 0:
                    self._condition.notify_all()

    @contextmanager
    def write_lock(self):
        with self._condition:
            self._writers_waiting += 1
            try:
                while self._writer_active or self._readers:
                    self._condition.wait()
            except BaseException:
                self._writers_waiting -= 1
                self._condition.notify_all()
                raise
            self._writers_waiting -= 1
            self._writer_active = True

        try:
            yield
        finally:
            with self._condition:
                self._writer_active = False
                self._condition.notify_all()
