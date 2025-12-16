# BlueZ Bug Report: GATT Services Not Exposed via D-Bus for Dual-Mode Device

## Summary

BlueZ 5.82 successfully connects to a dual-mode Bluetooth device (Millennium ChessLink) via LE transport and performs GATT service discovery at the HCI level, but fails to expose the discovered services via D-Bus. The `ServicesResolved` property becomes `1` (true), but the `UUIDs` property remains empty and no GATT service/characteristic D-Bus objects are created.

The same device works correctly with `gatttool` interactive mode, which performs GATT discovery directly without going through D-Bus.

## Environment

- **BlueZ version**: 5.82
- **Kernel**: Linux (Raspberry Pi OS, Debian-based)
- **Bluetooth adapter**: BCM43438 (Raspberry Pi built-in)
- **Device**: Millennium ChessLink chess board (dual-mode: BR/EDR + BLE)
- **Device address**: 34:81:F4:ED:78:34 (public)

## Steps to Reproduce

1. Ensure the device is not paired via classic Bluetooth
2. Enable `Experimental = true` in `/etc/bluetooth/main.conf` (required for `PreferredBearer`)
3. Restart bluetoothd
4. Run the following Python script:

```python
import dbus
import time

bus = dbus.SystemBus()

# Start LE-only discovery
adapter = dbus.Interface(
    bus.get_object('org.bluez', '/org/bluez/hci0'),
    'org.bluez.Adapter1'
)
adapter.SetDiscoveryFilter({'Transport': dbus.String('le')})
adapter.StartDiscovery()
time.sleep(10)

device_path = '/org/bluez/hci0/dev_34_81_F4_ED_78_34'

# Set PreferredBearer to force LE connection
device_props = dbus.Interface(
    bus.get_object('org.bluez', device_path),
    'org.freedesktop.DBus.Properties'
)
device_props.Set('org.bluez.Device1', 'PreferredBearer', dbus.String('le'))

# Connect
device = dbus.Interface(
    bus.get_object('org.bluez', device_path),
    'org.bluez.Device1'
)
device.Connect()
print('Connected')

# Wait for services to resolve
for i in range(15):
    time.sleep(1)
    resolved = device_props.Get('org.bluez.Device1', 'ServicesResolved')
    uuids = list(device_props.Get('org.bluez.Device1', 'UUIDs'))
    print(f'{i+1}s: ServicesResolved={resolved}, UUIDs={len(uuids)}')
    if len(uuids) > 0:
        print(f'UUIDs: {uuids}')
        break

# Check for GATT D-Bus objects
manager = dbus.Interface(
    bus.get_object('org.bluez', '/'),
    'org.freedesktop.DBus.ObjectManager'
)
objects = manager.GetManagedObjects()
gatt_objects = [p for p in objects.keys() if device_path in p and '/service' in p]
print(f'GATT service objects: {gatt_objects}')

device.Disconnect()
adapter.StopDiscovery()
```

## Expected Behavior

After `ServicesResolved` becomes `1`:
- `UUIDs` property should contain the discovered service UUIDs
- D-Bus objects should be created under the device path for services and characteristics (e.g., `/org/bluez/hci0/dev_34_81_F4_ED_78_34/service0001`)

## Actual Behavior

```
Connected
1s: ServicesResolved=0, UUIDs=0
2s: ServicesResolved=1, UUIDs=0
3s: ServicesResolved=1, UUIDs=0
...
15s: ServicesResolved=1, UUIDs=0
GATT service objects: []
```

- `ServicesResolved` becomes `1` after ~1 second
- `UUIDs` remains empty (`[]`)
- No GATT D-Bus objects are created

## btmon Capture

Running `btmon` during the connection shows that GATT discovery **is happening** at the HCI level:

```
ATT: Exchange MTU Request (0x02) len 2
  Client RX MTU: 517
ATT: Exchange MTU Response (0x03) len 2
  Server RX MTU: 160
ATT: Read By Group Type Request (0x10) len 6
  Handle range: 0x0001-0xffff
  Attribute group type: Primary Service (0x2800)
ATT: Read By Group Type Response (0x11) len 13
  Attribute data length: 6
  Attribute group list: 2 entries
  Handle range: 0x0001-0x0007
  UUID: Generic Access Profile (0x1800)
  Handle range: 0x0010-0x0020
  UUID: Device Information (0x180a)
ATT: Read By Group Type Response (0x11) len 21
  Attribute data length: 20
  Attribute group list: 1 entry
  Handle range: 0x0030-0x003d
  UUID: Vendor specific (49535343-fe7d-4ae5-8fa9-9fafd205e455)
```

The services are discovered correctly:
- Generic Access Profile (0x1800)
- Device Information (0x180a)
- Vendor specific service (49535343-fe7d-4ae5-8fa9-9fafd205e455)

However, the characteristic discovery response appears to be parsed incorrectly:

```
ATT: Read By Type Response (0x09) len 141
  Attribute data length: 21
  Attribute data list: 6 entries
  Handle: 0x0002
  Value[19]: 020300002a0400020500012a0600020700042a
      Properties: 0x02
        Read (0x02)
      Value Handle: 0x0003
      Value UUID: Vendor specific (2a040007-0200-062a-0100-050200042a00)
```

The `Value UUID` shown is malformed (`2a040007-0200-062a-0100-050200042a00`). This should be parsing short 16-bit UUIDs like `0x2a00`, `0x2a01`, etc., but BlueZ appears to be reading the wrong byte offsets.

## Workaround

Using `gatttool` in interactive mode works correctly:

```bash
$ gatttool -b 34:81:F4:ED:78:34 -I
[34:81:F4:ED:78:34][LE]> connect
Attempting to connect to 34:81:F4:ED:78:34
Connection successful
[34:81:F4:ED:78:34][LE]> primary
attr handle: 0x0001, end grp handle: 0x0007 uuid: 00001800-0000-1000-8000-00805f9b34fb
attr handle: 0x0010, end grp handle: 0x0020 uuid: 0000180a-0000-1000-8000-00805f9b34fb
attr handle: 0x0030, end grp handle: 0x003d uuid: 49535343-fe7d-4ae5-8fa9-9fafd205e455
[34:81:F4:ED:78:34][LE]> char-desc
handle: 0x0037, uuid: 0000fff2-0000-1000-8000-00805f9b34fb
handle: 0x003a, uuid: 0000fff1-0000-1000-8000-00805f9b34fb
...
```

`gatttool` correctly discovers the services and characteristics, including the `fff1` and `fff2` characteristics that the D-Bus layer fails to expose.

## Additional Notes

1. **Device is dual-mode**: The device advertises both BR/EDR (Serial Port Profile) and BLE. Without setting `PreferredBearer` to `le`, BlueZ attempts a BR/EDR connection and fails with `br-connection-profile-unavailable`.

2. **Connection is established**: `hcitool con` confirms an LE connection is active:
   ```
   < LE 34:81:F4:ED:78:34 handle 64 state 1 lm CENTRAL
   ```

3. **GATT Client is enabled**: `/etc/bluetooth/main.conf` has:
   ```
   [GATT]
   Client = true
   ReverseServiceDiscovery = true
   ```

4. **Cache was cleared**: The issue persists after removing `/var/lib/bluetooth/*/cache/*` and restarting bluetoothd.

5. **Other BLE devices work**: A Chessnut Air board (BLE-only) connects and has its GATT services properly exposed via D-Bus using the same code.

## Suspected Cause

The btmon output suggests BlueZ's GATT client is receiving valid ATT responses but failing to parse them correctly when building the D-Bus object tree. The malformed UUID in the btmon output (`2a040007-0200-062a-0100-050200042a00` instead of `0x2a00`) suggests a byte-offset or endianness issue in the ATT response parser.

This may be specific to how this device formats its ATT responses, or it may be a general issue with certain ATT response structures that hasn't been encountered before.

## Impact

Applications using the BlueZ D-Bus API (including the `bleak` Python library) cannot communicate with this device, even though the underlying BLE connection and GATT discovery work correctly at the HCI level.



