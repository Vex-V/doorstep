from doorstep.ring import webhooks


def test_sign_verify_roundtrip():
    body = webhooks.build("motion_detected", "dev1", 1786715596787, "human")
    header = webhooks.sign("secret", body)
    assert header.startswith("sha256=")
    assert webhooks.verify("secret", body, header)
    assert webhooks.verify("secret", body, header.removeprefix("sha256="))   # bare hex
    assert not webhooks.verify("other", body, header)
    assert not webhooks.verify("secret", body + b" ", header)
    assert not webhooks.verify("secret", body, None)


def test_parse_motion():
    body = webhooks.build("motion_detected", "dev1", 1786715596787, "human")
    hook = webhooks.parse(body)
    assert hook.type == "motion_detected"
    assert hook.device_id == "dev1"
    assert hook.timestamp_ms == 1786715596787
    assert hook.subtype == "human"
    assert hook.event_id == "dev1_motion_1786715596787"
    assert hook.request_id


def test_parse_ring_example():
    """The example payload from the Ring Partner API reference."""
    doc = {"meta": {"version": "1.1", "time": "2026-08-12T10:00:00Z",
                    "request_id": "abc", "account_id": "ava1.ring.account.XXXYYY"},
           "data": {"id": "dev_motion_1786715596787", "type": "motion_detected",
                    "attributes": {"source": "dev", "source_type": "devices",
                                   "timestamp": 1786715596787, "sub_type": "motion",
                                   "component_ids": ["0"]}}}
    hook = webhooks.parse(doc)
    assert (hook.request_id, hook.device_id, hook.subtype) == ("abc", "dev", "motion")
    assert hook.event_id == "dev_motion_1786715596787"


def test_non_device_source_has_no_device():
    doc = {"meta": {"request_id": "r"},
           "data": {"id": "x", "type": "app_integration_added",
                    "attributes": {"source": "acct", "source_type": "users"}}}
    assert webhooks.parse(doc).device_id is None
