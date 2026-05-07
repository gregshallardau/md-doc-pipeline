<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('md_doc_file_locks', function (Blueprint $table) {
            $table->id();

            // Relative path from workspace root (unique — only one lock per file)
            $table->string('file_path', 500)->unique();

            // Human-readable identifier of who holds the lock (name, email, or session id)
            $table->string('locked_by', 255);

            // Random UUID issued to the lock holder — used to verify lock ownership on
            // heartbeat, save, and release so one session can't hijack another's lock.
            $table->string('lock_key', 36)->unique();

            $table->timestamp('locked_at');
            $table->timestamp('expires_at')->index();

            $table->timestamps();
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('md_doc_file_locks');
    }
};
