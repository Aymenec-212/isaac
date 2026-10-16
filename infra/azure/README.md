# Retained offline deployment input validator

`check-parameters.py` is restored unchanged from approved M0/main `5116557`.
The retained `deploy/asr/test_deployment.py` imports its `validate` function.
The validator uses only Python's standard library and reads ARM parameter JSON;
it neither imports a template nor contacts Azure. It rejects non-public/non-/32
operator CIDRs, unpinned image versions and missing public-key prefixes.

The deleted Azure VM template and its Bicep parameter example are not restored:
they are not dependencies of this validator or the remaining ASR compose/image
helpers, and are not the approved M0 LiveKit/Modal deployment topology. Restoring
this security test dependency does not authorize or reactivate deployment.

Run from repository root (Python 3.12):

```sh
backend/.venv/bin/python -m unittest discover -s deploy/asr -p 'test_*.py' -v
```

Any future deployment needs its separately reviewed inputs, template and explicit
resource/budget authorization. This offline validator is not deployment approval.
