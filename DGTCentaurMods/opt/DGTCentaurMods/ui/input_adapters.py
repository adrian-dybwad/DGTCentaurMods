# minimal poller: map board button events to actions
def poll_actions_from_board():
    from DGTCentaurMods.board import board as boardmod

    # read one key event (non-blocking); 0 means “no key”
    try:
        boardmod.sendPacket(b'\x94', b'')
        resp = boardmod._ser_read(10000)
    except Exception:
        return None

    hx = resp.hex()[:-2]
    a1 = f"{boardmod.addr1:02x}"
    a2 = f"{boardmod.addr2:02x}"

    if hx == ("b10011" + a1 + a2 + "00140a0508000000007d3c"):  # UP
        return "UP"
    if hx == ("b10010" + a1 + a2 + "00140a05020000000061"):    # DOWN
        return "DOWN"
    if hx == ("b10011" + a1 + a2 + "00140a0510000000007d17"):  # TICK
        return "SELECT"
    if hx == ("b10011" + a1 + a2 + "00140a0501000000007d47"):  # BACK
        return "BACK"
    return None
