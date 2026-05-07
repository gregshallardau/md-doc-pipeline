# File locking

Pessimistic, database-backed locks ensure that only one user edits a given file at a time. This is essential when you're using git: without locking, two users editing the same file independently produce a merge conflict at commit time.

---

## Lock model

Every active lock is a row in `md_doc_file_locks`:

| Column | Type | Purpose |
|---|---|---|
| `id` | bigint PK | |
| `file_path` | varchar(500) UNIQUE | Workspace-relative path. The unique constraint is what enforces "one lock per file". |
| `locked_by` | varchar(255) | Display name (`auth()->user()->name`) or session ID — see `lock_user_source` config. |
| `lock_key` | varchar(36) UNIQUE | Random UUID issued to the lock-holder. The browser must present this on every save/refresh/release. |
| `locked_at` | timestamp | When the lock was acquired. |
| `expires_at` | timestamp INDEX | When the lock expires if not refreshed. |

The `lock_key` UUID is the security mechanism: another session that simply *knows* your file path can't release or refresh your lock without the key.

---

## Lifecycle

### Acquire

When a user opens a file:

1. `FileLockService::acquire($path, $userLabel)` first calls `purgeExpired()` to delete any expired rows (`expires_at < now()`).
2. It generates a UUID `lock_key` and tries to `INSERT` a new row with `expires_at = now() + lock_ttl_minutes`.
3. If the unique constraint on `file_path` fires (someone else already holds an unexpired lock), it returns `null`.
4. Otherwise it returns the `lock_key`. The Livewire component stores it in `$lockKey` and passes it to JS as `window.mdDocLockKey`.

### Heartbeat

Every `lock_ttl_minutes / 2` minutes (so 5 min for the 10-min default), `editor.js` sends:

```
POST /md-doc/lock/refresh
{ "path": "...", "lockKey": "..." }
```

`LockController::refresh()` calls `FileLockService::refresh()` which runs:

```sql
UPDATE md_doc_file_locks
   SET expires_at = NOW() + INTERVAL <ttl> MINUTE
 WHERE file_path = ? AND lock_key = ? AND expires_at > NOW()
```

If the update affects 0 rows (the lock expired between heartbeats), the response `{ "ok": false }` triggers a Livewire event that puts the editor in read-only mode and shows a "Lock expired" toast.

### Release

Three release paths:

| Trigger | Mechanism |
|---|---|
| User opens a different file | Livewire `loadFile()` calls `releaseLock()` before loading the new file |
| User closes tab / navigates away | `window.beforeunload` → `navigator.sendBeacon('/md-doc/lock/release', ...)` |
| Lock expires naturally | Next `purgeExpired()` deletes it |

`sendBeacon` is fire-and-forget — the browser keeps the request alive even after the page is unloaded, but doesn't wait for a response. This is the most reliable way to clean up across tab close, navigation, and crashes.

### Steal (request edit)

When a file is locked by someone else, the toolbar shows **Request edit** instead of Save. Clicking it calls `tryStealLock()`:

```php
$existing = $this->lockService->getLock($this->path);
if ($existing !== null) {
    // Still locked — not yet expired. Show notification with remaining time.
    return;
}
// Genuinely expired — try to acquire.
$this->acquireLock($this->path);
```

This means you can never silently steal an active lock — only one that has fully timed out.

---

## Read-only mode

When `acquire()` returns `null`, the Livewire component sets:

- `$isReadOnly = true`
- `$lockOwner = $existingLock->locked_by`
- `$lockKey = null`

The Blade template then:

- Hides the **Save** and **Build** buttons
- Shows the badge: `🔒 Read-only · locked by <name>`
- Shows the **Request edit** button
- Initialises Monaco with `readOnly: true`

The user can still browse the file, switch tabs, view history, run diff — they just can't change anything.

---

## Edge cases

### Forgotten browser tab

If a user opens a file and walks away, the heartbeat keeps the lock alive *forever* — that's a problem.

Mitigations available:

1. **Reduce TTL**: set `MD_DOC_LOCK_TTL=5` so abandoned tabs lose their lock within 5 min.
2. **Detect inactivity client-side**: not implemented today, but trivial to add — pause the heartbeat if `document.hidden` or no keyboard activity for N minutes.

### PHP crash mid-acquire

If the request fails between INSERT and response delivery, the lock is held but no client knows the key. Outcomes:

- The original user can't reload to recover (the stale row will block them)
- They wait `lock_ttl_minutes` for the lock to expire naturally
- Or an admin runs:
  ```sql
  DELETE FROM md_doc_file_locks WHERE file_path = '...';
  ```

### Sleeping laptops / network drops

The heartbeat fails silently for a single missed beat (network blip), but the next successful beat re-extends the TTL. If the user is offline for longer than `lock_ttl_minutes`, the lock expires; when they return, the next heartbeat gets `{ ok: false }` and the editor switches to read-only with a notification. Reload to acquire fresh.

### Two browser tabs from the same user

Each tab is treated as a separate session — the second tab opens read-only. This is intentional: the lock_key is tied to the session, so swapping tabs doesn't transfer the lock.

If you need shared editing across tabs for the same user, look into Laravel Echo presence channels — but that's a substantially more complex feature than what's here today.

---

## Operations

### Manually clear a stuck lock

```bash
php artisan tinker
>>> \MdDoc\FilamentMdDoc\Models\FileLock::where('file_path', 'workspace/acme/proposal.md')->delete();
```

### Inspect active locks

```bash
php artisan tinker
>>> \MdDoc\FilamentMdDoc\Models\FileLock::where('expires_at', '>', now())->get(['file_path', 'locked_by', 'expires_at']);
```

### Schedule cleanup

The plugin auto-purges expired locks at the start of every `acquire()` call, so under normal use the table stays small. If you want extra hygiene:

```php
// app/Console/Kernel.php
$schedule->call(fn () => (new \MdDoc\FilamentMdDoc\Services\FileLockService())->purgeExpired())
    ->everyFifteenMinutes();
```

---

## Endpoints

| Route | Purpose |
|---|---|
| `POST /md-doc/lock/refresh` | Heartbeat — extend TTL. Used by `setInterval` in JS. |
| `POST /md-doc/lock/release` | Release — used by `navigator.sendBeacon` on tab close. |

Both expect JSON body `{ "path": "...", "lockKey": "..." }`. The release endpoint always returns 204; the refresh endpoint returns `{ "ok": bool }`.
