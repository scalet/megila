"""Durable job queue.

Future home of the SQLite WAL queue with lease and heartbeat. The queue is a
package so the storage implementation can sit beside its interface.
"""
