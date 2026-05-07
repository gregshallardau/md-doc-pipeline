<?php

namespace MdDoc\FilamentMdDoc\Services;

use Illuminate\Database\UniqueConstraintViolationException;
use Illuminate\Support\Str;
use MdDoc\FilamentMdDoc\Models\FileLock;

class FileLockService
{
    /**
     * Try to acquire a lock on the given file path.
     *
     * Returns the lock_key (UUID) on success, or null if the file is already
     * locked by someone else (or an unexpired lock exists).
     */
    public function acquire(string $path, string $lockedBy): ?string
    {
        $this->purgeExpired();

        $ttl     = (int) config('md-doc.lock_ttl_minutes', 10);
        $lockKey = Str::uuid()->toString();

        try {
            FileLock::create([
                'file_path' => $path,
                'locked_by' => $lockedBy,
                'lock_key'  => $lockKey,
                'locked_at' => now(),
                'expires_at' => now()->addMinutes($ttl),
            ]);

            return $lockKey;
        } catch (UniqueConstraintViolationException) {
            // Another session holds an unexpired lock
            return null;
        }
    }

    /**
     * Release a lock.  Only succeeds when the caller presents the correct lock_key,
     * so one session cannot release another session's lock.
     */
    public function release(string $path, string $lockKey): void
    {
        FileLock::where('file_path', $path)
                ->where('lock_key', $lockKey)
                ->delete();
    }

    /**
     * Extend the TTL of an existing lock.  Returns false if the lock has already
     * expired or the lock_key does not match (session was hijacked or timed out).
     */
    public function refresh(string $path, string $lockKey): bool
    {
        $ttl = (int) config('md-doc.lock_ttl_minutes', 10);

        $rows = FileLock::where('file_path', $path)
                        ->where('lock_key', $lockKey)
                        ->where('expires_at', '>', now())
                        ->update(['expires_at' => now()->addMinutes($ttl)]);

        return $rows > 0;
    }

    /**
     * Return the active (non-expired) lock for a path, or null if unlocked.
     */
    public function getLock(string $path): ?FileLock
    {
        return FileLock::where('file_path', $path)
                       ->where('expires_at', '>', now())
                       ->first();
    }

    /**
     * Check that the caller still holds a valid lock.
     */
    public function isLockedByKey(string $path, string $lockKey): bool
    {
        return FileLock::where('file_path', $path)
                       ->where('lock_key', $lockKey)
                       ->where('expires_at', '>', now())
                       ->exists();
    }

    /**
     * Return a map of file_path → locked_by for all currently active locks.
     * Used by the file tree to render lock badges.
     */
    public function activeLocks(): array
    {
        return FileLock::where('expires_at', '>', now())
                       ->pluck('locked_by', 'file_path')
                       ->toArray();
    }

    /**
     * Static convenience wrapper for use in Blade includes where DI is unavailable.
     */
    public static function staticActiveLocks(): array
    {
        return (new static())->activeLocks();
    }

    /**
     * Delete all expired lock rows.  Called automatically before acquire().
     */
    public function purgeExpired(): void
    {
        FileLock::where('expires_at', '<', now())->delete();
    }

    /**
     * Resolve the display name for the current user based on config.
     */
    public function currentUserLabel(): string
    {
        if (config('md-doc.lock_user_source') === 'auth' && auth()->check()) {
            $user = auth()->user();
            return $user->name ?? $user->email ?? (string) $user->getKey();
        }

        return session()->getId();
    }
}
