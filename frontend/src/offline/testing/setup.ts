/**
 * A real IndexedDB implementation for the test run.
 *
 * `fake-indexeddb` is the actual W3C algorithm over an in-memory backing store,
 * not a stub — transactions, key ranges and indexes behave as they do in a
 * browser. A hand-written mock would agree with whatever the queue happens to
 * do, which is the opposite of a test.
 */
import "fake-indexeddb/auto";
