<?php

namespace MdDoc\FilamentMdDoc\Models;

use Illuminate\Database\Eloquent\Model;

class FileLock extends Model
{
    protected $table = 'md_doc_file_locks';

    protected $fillable = [
        'file_path',
        'locked_by',
        'lock_key',
        'locked_at',
        'expires_at',
    ];

    protected $casts = [
        'locked_at'  => 'datetime',
        'expires_at' => 'datetime',
    ];

    public function isExpired(): bool
    {
        return $this->expires_at->isPast();
    }

    public function minutesRemaining(): int
    {
        return max(0, (int) now()->diffInMinutes($this->expires_at, false));
    }
}
