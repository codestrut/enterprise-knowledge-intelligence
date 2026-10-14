import threading

import pytest

from src.api.rwlock import ReadWriteLock


def _start(target):
    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread


def _wait_until(condition, timeout=5.0):
    done = threading.Event()

    def poll():
        while not condition():
            if done.wait(0.01):
                return

    thread = _start(poll)
    thread.join(timeout)
    done.set()
    return condition()


def test_readers_run_concurrently():
    lock = ReadWriteLock()
    barrier = threading.Barrier(2, timeout=5)
    errors = []

    def reader():
        try:
            with lock.read_lock():
                barrier.wait()  # only passes if both readers hold the lock
        except Exception as exc:
            errors.append(exc)

    threads = [_start(reader), _start(reader)]
    for thread in threads:
        thread.join(10)

    assert errors == []
    assert not any(thread.is_alive() for thread in threads)


def test_writer_waits_for_active_reader():
    lock = ReadWriteLock()
    reader_in = threading.Event()
    release_reader = threading.Event()
    writer_done = threading.Event()

    def reader():
        with lock.read_lock():
            reader_in.set()
            release_reader.wait(5)

    def writer():
        with lock.write_lock():
            writer_done.set()

    reader_thread = _start(reader)
    assert reader_in.wait(5)
    writer_thread = _start(writer)

    assert not writer_done.wait(0.2)  # blocked while the reader is active
    release_reader.set()
    assert writer_done.wait(5)

    reader_thread.join(5)
    writer_thread.join(5)


def test_waiting_writer_goes_before_new_readers():
    lock = ReadWriteLock()
    order = []
    first_reader_in = threading.Event()
    release_first_reader = threading.Event()
    second_reader_in = threading.Event()

    def first_reader():
        with lock.read_lock():
            first_reader_in.set()
            release_first_reader.wait(5)

    def writer():
        with lock.write_lock():
            order.append("writer")

    def second_reader():
        with lock.read_lock():
            order.append("second_reader")
            second_reader_in.set()

    threads = [_start(first_reader)]
    assert first_reader_in.wait(5)
    threads.append(_start(writer))
    assert _wait_until(lambda: lock._writers_waiting == 1)
    threads.append(_start(second_reader))

    # The second reader must queue behind the waiting writer.
    assert not second_reader_in.wait(0.2)
    release_first_reader.set()
    assert second_reader_in.wait(5)

    for thread in threads:
        thread.join(5)
    assert order == ["writer", "second_reader"]


def test_writer_excludes_readers():
    lock = ReadWriteLock()
    writer_in = threading.Event()
    release_writer = threading.Event()
    reader_in = threading.Event()

    def writer():
        with lock.write_lock():
            writer_in.set()
            release_writer.wait(5)

    def reader():
        with lock.read_lock():
            reader_in.set()

    writer_thread = _start(writer)
    assert writer_in.wait(5)
    reader_thread = _start(reader)

    assert not reader_in.wait(0.2)
    release_writer.set()
    assert reader_in.wait(5)

    writer_thread.join(5)
    reader_thread.join(5)


def test_lock_is_released_when_the_body_raises():
    lock = ReadWriteLock()

    with pytest.raises(RuntimeError):
        with lock.write_lock():
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        with lock.read_lock():
            raise RuntimeError("boom")

    reacquired = threading.Event()

    def acquire_both():
        with lock.write_lock():
            pass
        with lock.read_lock():
            reacquired.set()

    thread = _start(acquire_both)
    assert reacquired.wait(5)
    thread.join(5)
