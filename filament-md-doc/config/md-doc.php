<?php

return [
    /*
     * Absolute path to the workspace directory that contains your md-doc projects.
     * All file reads and writes are sandboxed to this directory.
     */
    'workspace_path' => env('MD_DOC_WORKSPACE', base_path('workspace')),
];
