<?php

use Illuminate\Support\Facades\Route;
use MdDoc\FilamentMdDoc\Http\Controllers\LockController;
use MdDoc\FilamentMdDoc\Livewire\DocumentEditor;

/*
 * These routes are loaded by MdDocServiceProvider via loadRoutesFrom().
 */

// Editor pages
Route::get('/md-doc/editor', DocumentEditor::class)
    ->name('md-doc.editor');

Route::get('/md-doc/editor/{path}', DocumentEditor::class)
    ->where('path', '.*')
    ->name('md-doc.editor.path');

// Lock API — lightweight JSON endpoints (not Livewire, so beacon works on unload)
Route::post('/md-doc/lock/release', [LockController::class, 'release'])
    ->name('md-doc.lock.release');

Route::post('/md-doc/lock/refresh', [LockController::class, 'refresh'])
    ->name('md-doc.lock.refresh');
