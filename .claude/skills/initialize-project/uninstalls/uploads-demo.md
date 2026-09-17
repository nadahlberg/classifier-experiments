# Uninstall the uploads demo

Removes the `DemoUpload` model, its endpoints, and the uploads page.
The storage backends stay — `STORAGES`, the S3/Spaces machinery, the
`private` alias, and the storage health probes are deploy
infrastructure, not demo code. **This removes a model: run the
migration reset afterwards.**

## Remove

1. In `clx/app/models/demo.py`: `demo_upload_storage`,
   `demo_upload_path`, and `DemoUpload` (drop the re-export from
   `clx/app/models/__init__.py`).
2. In `clx/app/services/demo.py`: `MAX_UPLOAD_FILES`,
   `MAX_UPLOAD_SIZE`, `demo_upload_create_batch`, and
   `demo_upload_delete`.
3. In `clx/app/selectors/demo.py`: `demo_upload_list` and
   `demo_upload_get`.
4. In `clx/app/api/demos.py`: `upload_list`, `upload_create`,
   `upload_delete`, `upload_file`, `upload_download`, `_stream`, and
   `_upload`; in `clx/app/urls.py`, the five `uploads/` entries
   in `demos_api_patterns`.
5. The `uploads` view in `clx/app/views/demos.py` (and its
   `MAX_UPLOAD_*` import), the `path("uploads/", ...)` entry in
   `demos_view_patterns` in `clx/app/urls.py`,
   `clx/app/templates/pages/demos/uploads.html`, and the Uploads
   tile in `clx/app/templates/pages/demos/index.html`.

## The edges

6. `clx/app/services/user.py`: `user_delete` loops over
   `DemoUpload` to purge bucket objects — drop the loop and the
   import, keeping the `user.delete()`.
7. `clx/app/api/utils/decorators.py`: delete `frame_self` (its
   only consumer was `upload_file`) and its re-export in
   `clx/app/api/utils/__init__.py`.
8. `clx/app/tests/conftest.py`: delete the `memory_storage`
   fixture and the `DemoUpload` import.
9. Delete `clx/app/tests/test_uploads.py`. In
   `clx/app/tests/test_csp.py`, remove the upload
   inline-stream test and the `demo_upload_create_batch` import —
   and keep its `form-action` reasoning intact. In
   `clx/app/tests/test_user.py`, rework the account-deletion
   test to stop creating uploads; keep the row-deletion assertions.

Grep CLAUDE.md for `upload` and prune, then run the migration reset
and the verify suite.
