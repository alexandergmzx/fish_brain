"""netwatch.Decider: when the board raises and drops its own Wi-Fi."""
from fish_brain.netwatch import AP, CLIENT, TRYING, Decider, Settings, settings_from

S = Settings(ap_profile="fish-ap")


def run(d, t0, t1, active="", stations=0, pinned=False, dt=2.0):
    """Step from t0 to t1; returns [(t, action)] for every action."""
    out, t = [], t0
    while t <= t1:
        a = d.step(t, active, stations, pinned)
        if a:
            out.append((t, a))
        t += dt
    return out


def started(now=0.0):
    d = Decider(S)
    d.start(now)
    return d


def test_no_known_network_raises_the_access_point_after_the_wait():
    d = started()
    assert run(d, 0, 44) == []
    assert run(d, 46, 46) == [(46, "up")] and d.state == AP
    assert run(d, 48, 64) == []                     # coming up: no second "up"
    assert run(d, 66, 70, active="fish-ap", stations=1) == []


def test_a_lost_client_waits_the_loss_time():
    d = started()
    run(d, 0, 10, active="IZZI")
    assert d.state == CLIENT
    assert run(d, 100, 128) == []
    assert run(d, 130, 130) == [(130, "up")]


def test_an_empty_access_point_tries_the_known_networks_and_backs_off():
    d = started()
    run(d, 0, 46)                                   # raised at 46
    acts = run(d, 48, 106, active="fish-ap")
    assert acts and acts[0] == (106, "down") and d.state == TRYING   # 60 s idle after 46
    acts = run(d, 108, 150)                         # nothing joined within the 40 s try
    assert acts == [(146, "up")] and d.state == AP
    # The next idle try waits for the backoff, not just the idle time.
    acts = run(d, 148, 400, active="fish-ap")
    assert acts and acts[0][0] >= 106 + 40 + 60 and acts[0][1] == "down"


def test_a_connected_phone_keeps_the_access_point_up():
    d = started()
    run(d, 0, 46)
    assert run(d, 48, 1000, active="fish-ap", stations=1) == []


def test_the_pin_raises_it_at_once_and_never_drops_it():
    d = started()
    assert run(d, 0, 0, pinned=True) == [(0, "up")]
    assert run(d, 2, 1000, active="fish-ap", pinned=True) == []


def test_a_known_network_found_during_a_try_wins():
    d = started()
    run(d, 0, 46)
    run(d, 48, 106, active="fish-ap")               # down at 106
    assert run(d, 110, 120, active="yes") == [] and d.state == CLIENT and d.tries == 0


def test_settings_read_the_env_with_defaults():
    s = settings_from({"FISH_NET_AP_PROFILE": "fish-ap", "FISH_NET_CLIENT_WAIT_S": "30",
                       "FISH_NET_LOSS_S": "bad"})
    assert s.ap_profile == "fish-ap" and s.client_wait_s == 30 and s.loss_s == 30.0
    assert settings_from({}).ap_profile == ""
