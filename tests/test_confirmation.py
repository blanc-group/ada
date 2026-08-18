from ada_bridge.confirmation import ConfirmationPolicy, is_write_tool


def test_read_verbs_are_not_writes():
    for name in ("ghl_contacts_list", "meta_insights_get", "n8n_executions_search"):
        assert not is_write_tool(name)


def test_write_and_unknown_verbs_are_writes():
    for name in ("ghl_contacts_create", "meta_campaign_pause", "x_frobnicate_y"):
        assert is_write_tool(name)


def test_read_tool_passes_immediately():
    policy = ConfirmationPolicy()
    assert policy.check("ghl_contacts_list", {"limit": 5}) is True


def test_write_tool_requires_second_identical_call():
    now = [0.0]
    policy = ConfirmationPolicy(ttl_seconds=120, clock=lambda: now[0])
    args = {"name": "Mario"}
    assert policy.check("ghl_contacts_create", args) is False
    assert policy.check("ghl_contacts_create", args) is True
    # consumed: a third call re-arms
    assert policy.check("ghl_contacts_create", args) is False


def test_different_args_do_not_confirm_each_other():
    policy = ConfirmationPolicy()
    assert policy.check("ghl_contacts_create", {"name": "Mario"}) is False
    assert policy.check("ghl_contacts_create", {"name": "Luigi"}) is False


def test_confirmation_expires_after_ttl():
    now = [0.0]
    policy = ConfirmationPolicy(ttl_seconds=120, clock=lambda: now[0])
    assert policy.check("ghl_contacts_create", {}) is False
    now[0] = 121.0
    assert policy.check("ghl_contacts_create", {}) is False
