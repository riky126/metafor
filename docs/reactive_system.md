# Metafor Core Reactive System

The core of Metafor is a fine-grained reactive system based on the **Signal** pattern (similar to SolidJS or Angular Signals). It allows for automatic dependency tracking and efficient updates without a Virtual DOM diffing overhead.

## Core Primitives

The system relies on two main primitives: **Signals** (State) and **Effects** (Reactions).

### 1. Signal (`Signal`)
A Signal is a wrapper around a value that can be observed.
-   **Read (`signal()` or `signal.get()`)**: Returns the current value and **automatically registers** the calling context (usually an Effect) as a dependency.
-   **Write (`signal.set(val)`)**: Updates the value and **notifies** all registered subscribers (Effects) that depend on this signal.

### 2. Effect (`Effect`)
An Effect is a function that runs in response to signal changes.
-   **Auto-tracking**: When an effect runs, it sets itself as the global `_current_effect`. Any signal read during the execution registers this effect as a subscriber.
-   **Dynamic Dependencies**: Dependencies are cleared and re-collected on every run. If a signal is inside an `if` block and is no longer reached, it stops triggering the effect.
-   **Cleanup**: Effects support cleanup callbacks (via `on_dispose`) to handle resource teardown.

### 3. Derived State (`Memo` and `LinkedSignal`)
-   **Memo**: A computed signal that caches its value. It only recomputes when its dependencies change.
-   **LinkedSignal**: A special signal that updates based on dependencies but can also be manually overridden (similar to Angular's LinkedSignal).

## The Reactivity Cycle

```
┌─────────────────────────────────────────────────────────────────────┐
│                            STATE (Signals)                           │
│  ┌────────────────────────┐         ┌────────────────────────┐       │
│  │       Signal A         │         │       Signal B         │       │
│  │    (Value Wrapper)     │         │    (Value Wrapper)     │       │
│  └───────────┬────────────┘         └───────────┬────────────┘       │
└──────────────┼──────────────────────────────────┼────────────────────┘
               │                                  │
               │ 1. Read (Track)                  │ 1. Read (Track)
               ▼                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         LOGIC (Computation)                          │
│                                                                     │
│  ┌────────────────────────────────────────────────────────┐         │
│  │                   EFFECT / COMPUTED                    │         │
│  │                 (Function Execution)                   │         │
│  │                                                        │         │
│  │   • Sets _current_effect = self                        │         │
│  │   • Runs function                                      │         │
│  │   • Registers as subscriber to referenced signals      │         │
│  └───────────────────────────┬────────────────────────────┘         │
└──────────────────────────────┼──────────────────────────────────────┘
                               │
                               │ 2. Execute / Re-run
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         VIEW / OUTPUT                                │
│                                                                     │
│  ┌────────────────────────────────────────────────────────┐         │
│  │                      DOM UPDATE                        │         │
│  │         (Update textContent, attributes, etc.)         │         │
│  └────────────────────────────────────────────────────────┘         │
└─────────────────────────────────────────────────────────────────────┘

                                ▲
                                │ 5. Re-run Effect
                                │
┌───────────────────────────────┴─────────────────────────────────────┐
│                           UPDATE CYCLE                               │
│                                                                     │
│  ┌───────────────┐        ┌───────────────┐        ┌─────────────┐  │
│  │  User Action  │───────►│  Signal.set() │───────►│  Notify()   │  │
│  └───────────────┘   3.   └───────────────┘   4.   └─────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### Detailed Flow

1.  **Tracking Phase**:
    *   When an `Effect` starts running, it becomes the `_current_effect`.
    *   It executes its function.
    *   When code reads `signal()`, the signal checks `_current_effect`.
    *   The signal adds the effect to its `_subscribers` list.
    *   The effect adds the signal to its `dependencies` set.

2.  **Trigger Phase**:
    *   Code calls `signal.set(new_value)`.
    *   The signal updates its internal value.
    *   The signal iterates through `_subscribers` and calls `notify()`.
    *   The `Effect` marks itself as `dirty` and schedules a run (synchronously or batched).

## Deep Reactivity

Metafor support "deep" reactivity for dictionaries and lists.
-   When a `dict` or `list` is passed to `create_signal(..., deep=True)`, it is wrapped in `ReactiveDict` or `ReactiveList`.
-   Operations like `apppend`, `pop`, or `__setitem__` on these proxy objects trigger the parent signal's subscribers.
-   Property-level subscription (`_prop_subscribers`) allows effects to listen only to specific keys of an object, avoiding unnecessary re-renders when other unrelated keys change.

## Global State Management

The core system handles synchronization globally:
-   `_current_effect`: Tracks the currently executing effect for dependency gathering.
-   `batch_updates`: Allows multiple signal updates to trigger effects only once at the end of the batch.
-   `untrack()`: Utility to read a signal without establishing a dependency.
