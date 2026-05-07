<?php

namespace MdDoc\FilamentMdDoc\Http\Controllers;

use Illuminate\Http\Request;
use Illuminate\Http\Response;
use Illuminate\Routing\Controller;
use MdDoc\FilamentMdDoc\Services\FileLockService;

class LockController extends Controller
{
    public function __construct(protected FileLockService $lockService) {}

    /**
     * Release a lock via navigator.sendBeacon() on page unload.
     *
     * Beacon sends JSON body, not form data, so we decode from content.
     * Returns 204 regardless — the client does not wait for a response.
     */
    public function release(Request $request): Response
    {
        $data    = json_decode($request->getContent(), true) ?? [];
        $path    = $data['path']    ?? null;
        $lockKey = $data['lockKey'] ?? null;

        if ($path && $lockKey) {
            $this->lockService->release($path, $lockKey);
        }

        return response()->noContent();
    }

    /**
     * Heartbeat: extend the TTL of an existing lock.
     * Called every (lock_ttl / 2) minutes from the editor's JS interval.
     */
    public function refresh(Request $request): \Illuminate\Http\JsonResponse
    {
        $path    = $request->input('path');
        $lockKey = $request->input('lockKey');

        if (!$path || !$lockKey) {
            return response()->json(['ok' => false, 'reason' => 'missing params'], 422);
        }

        $ok = $this->lockService->refresh($path, $lockKey);

        return response()->json(['ok' => $ok]);
    }
}
