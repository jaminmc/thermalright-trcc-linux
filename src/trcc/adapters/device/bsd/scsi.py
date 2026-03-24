"""FreeBSD SCSI passthrough via camcontrol.

On FreeBSD, SCSI passthrough uses the CAM (Common Access Method)
subsystem. Devices appear as /dev/pass* and can be accessed via
`camcontrol cmd` subprocess calls.

This is the FreeBSD equivalent of Linux sg_raw.

Requires: camcontrol (part of base FreeBSD)
"""
from __future__ import annotations

import logging
import os
import subprocess

log = logging.getLogger(__name__)


class BSDScsiTransport:
    """Send raw SCSI commands to a device on FreeBSD via camcontrol.

    Uses `camcontrol cmd /dev/passN` to send CDBs and data.
    Part of the base system — no additional packages needed.

    Usage:
        transport = BSDScsiTransport('/dev/pass0')
        transport.open()
        transport.send_cdb(cdb_bytes, data_bytes)
        transport.close()
    """

    def __init__(self, device: str) -> None:
        self._device = device
        self._is_open = False

    def open(self) -> bool:
        """Verify the pass device exists and is accessible."""
        if not os.path.exists(self._device):
            log.error("BSD SCSI device %s not found", self._device)
            return False

        # Check we can stat the device (permissions check)
        try:
            os.stat(self._device)
            self._is_open = True
            return True
        except PermissionError:
            log.error("No permission to access %s — try sudo", self._device)
            return False
        except Exception:
            log.exception("Failed to open BSD SCSI device %s", self._device)
            return False

    def close(self) -> None:
        """Release the device."""
        self._is_open = False

    def send_cdb(
        self,
        cdb: bytes,
        data: bytes,
        *,
        timeout: int = 5,
    ) -> bool:
        """Send a SCSI CDB with data payload via camcontrol.

        Args:
            cdb: SCSI Command Descriptor Block (6-16 bytes)
            data: Data to send (frame bytes for LCD)
            timeout: Timeout in seconds

        Returns:
            True if transfer succeeded
        """
        if not self._is_open:
            log.error("BSD SCSI device not open")
            return False

        # Format CDB as hex string for camcontrol
        cdb_hex = ' '.join(f'{b:02x}' for b in cdb)
        data_len = len(data)

        try:
            # camcontrol cmd <device> -c "<cdb>" -o <len> [-d <data>]
            cmd = [
                'camcontrol', 'cmd', self._device,
                '-c', cdb_hex,
                '-o', str(data_len),
            ]
            result = subprocess.run(
                cmd,
                input=data,
                capture_output=True,
                timeout=timeout,
            )
            if result.returncode != 0:
                log.warning(
                    "camcontrol cmd failed (rc=%d): %s",
                    result.returncode,
                    result.stderr.decode(errors='replace').strip(),
                )
                return False
            return True

        except subprocess.TimeoutExpired:
            log.error("BSD SCSI transfer timed out after %ds", timeout)
            return False
        except Exception:
            log.exception("BSD SCSI transfer failed")
            return False

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *exc):
        self.close()


def bsd_scsi_resolver(vid: int, pid: int) -> str | None:
    """Map a VID:PID to its /dev/passN path via camcontrol devlist.

    Injected into DeviceDetector by builder on FreeBSD.
    """
    try:
        result = subprocess.run(
            ['camcontrol', 'devlist'],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return None
        for line in result.stdout.splitlines():
            if 'pass' in line:
                paren = line.rsplit('(', 1)
                if len(paren) == 2:
                    for d in paren[1].rstrip(')').split(','):
                        d = d.strip()
                        if d.startswith('pass'):
                            return f'/dev/{d}'
    except Exception:
        log.debug("camcontrol devlist failed")
    return None
