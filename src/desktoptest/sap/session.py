"""
sap/session.py — SAP GUI Scripting wrapper (the perceive + act layer).

This is the desktop equivalent of your Playwright MCP bridge. Instead of a
browser DOM it drives the SAP GUI Scripting COM object model via pywin32:

    GetObject("SAPGUI") -> application -> connection -> session -> findById(...)

Every element on a SAP screen has a STABLE id like:
    wnd[0]/usr/txtRSYST-BNAME          (the user field on the logon screen)
    wnd[0]/tbar[0]/okcd                (the command/transaction box)
That stability is why SAP GUI is so automatable — no coordinates, no guessing.

Cross-platform note: pywin32 + COM are Windows-only. On macOS/Linux (or when
SAP_DRY_RUN=true) this class runs in DRY-RUN mode: it logs intended actions and
returns mock element trees, so you can develop the engine off-Windows. Real runs
must execute on a Windows node with SAP GUI for Windows + scripting enabled.
"""

from __future__ import annotations

import logging
import os
import platform
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Defaults tunable via environment variables (no code change needed on-site).
_BUSY_TIMEOUT  = float(os.getenv("SAP_BUSY_TIMEOUT", "15"))   # seconds
_BUSY_POLL     = float(os.getenv("SAP_BUSY_POLL",    "0.1"))  # seconds

logger = logging.getLogger("desktoptest.sap")

_DEFAULT_SHCUT_PATH = r"C:\Program Files (x86)\SAP\FrontEnd\SAPgui\sapshcut.exe"


class SapError(RuntimeError):
    pass


@dataclass
class SapElement:
    """A normalised view of one SAP GUI scripting element."""
    id: str
    type: str = ""
    name: str = ""
    text: str = ""
    tooltip: str = ""
    changeable: bool = True
    children: List["SapElement"] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "type": self.type, "name": self.name,
            "text": self.text, "tooltip": self.tooltip,
            "changeable": self.changeable,
            "children": [c.to_dict() for c in self.children],
        }


class SapSession:
    """
    Attach to a running SAP GUI session and drive it.

    Usage:
        sap = SapSession.attach()        # connects to the open SAP GUI
        sap.start_transaction("VA01")
        sap.set_text("wnd[0]/usr/ctxtVBAK-AUART", "OR")
        sap.send_vkey(0)                 # Enter
        val = sap.get_text("wnd[0]/sbar")
    """

    def __init__(self, session=None, dry_run: bool = False, connection=None):
        self._session = session
        self.dry_run = dry_run
        self._connection = connection  # tracked only when we launched it (see launch()/close())

    # ── lifecycle ────────────────────────────────────────────────────────────
    @classmethod
    def attach(cls, connection: Optional[str] = None,
               dry_run: Optional[bool] = None) -> "SapSession":
        """Attach to whatever SAP GUI session is already open (manual SAP Logon)."""
        if dry_run is None:
            dry_run = os.getenv("SAP_DRY_RUN", "false").lower() == "true"
        if dry_run or platform.system() != "Windows":
            if not dry_run:
                logger.warning("Not on Windows — forcing SAP dry-run mode.")
            return cls(session=None, dry_run=True)

        try:
            import win32com.client  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise SapError("pywin32 not installed (pip install pywin32)") from e

        try:
            sap_gui = win32com.client.GetObject("SAPGUI")
            app = sap_gui.GetScriptingEngine
            if app.Connections.Count == 0:
                raise SapError(
                    "No open SAP connection. Log in via SAP Logon first, and "
                    "ensure scripting is enabled (sapgui/user_scripting=TRUE)."
                )
            conn = app.Connections(0)
            session = conn.Sessions(0)
            logger.info("Attached to SAP session: %s", session.Id)
            # connection is intentionally NOT tracked here — attach() reuses a
            # session you opened yourself, so close() must not touch it.
            return cls(session=session, dry_run=False)
        except SapError:
            raise
        except Exception as e:  # noqa: BLE001
            raise SapError(f"Could not attach to SAP GUI: {e}") from e

    @classmethod
    def launch(cls, system: Optional[str] = None, client: Optional[str] = None,
               shcut_path: Optional[str] = None, timeout: Optional[float] = None,
               dry_run: Optional[bool] = None) -> "SapSession":
        """
        Launch a brand-new SAP GUI session via sapshcut.exe (SSO login — no
        username/password needed) and wait for it to come up, instead of relying
        on a session you opened manually beforehand. Use with close() to give
        each test run a clean SAP session.
        """
        if dry_run is None:
            dry_run = os.getenv("SAP_DRY_RUN", "false").lower() == "true"
        if dry_run or platform.system() != "Windows":
            if not dry_run:
                logger.warning("Not on Windows — forcing SAP dry-run mode.")
            return cls(session=None, dry_run=True)

        system = system or os.getenv("SAP_CONNECTION", "")
        client = client or os.getenv("SAP_CLIENT", "")
        if not system or not client:
            raise SapError(
                "SAP_CONNECTION and SAP_CLIENT must be set in .env to launch a "
                "fresh SAP GUI session via sapshcut.exe."
            )
        shcut_path = shcut_path or os.getenv("SAP_SHCUT_PATH", _DEFAULT_SHCUT_PATH)
        timeout = timeout if timeout is not None else float(os.getenv("SAP_LAUNCH_TIMEOUT", "60"))

        try:
            import subprocess
            import win32com.client  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise SapError("pywin32 not installed (pip install pywin32)") from e

        baseline = 0
        try:
            baseline = win32com.client.GetObject("SAPGUI").GetScriptingEngine.Connections.Count
        except Exception:  # noqa: BLE001 — no SAP GUI process running yet
            pass

        logger.info("launching SAP GUI: %s -system=%s -client=%s", shcut_path, system, client)
        try:
            subprocess.Popen([shcut_path, f"-system={system}", f"-client={client}"])
        except OSError as e:
            raise SapError(f"Could not launch sapshcut.exe at {shcut_path!r}: {e}") from e

        deadline = time.monotonic() + timeout
        conn = None
        while time.monotonic() < deadline:
            try:
                app = win32com.client.GetObject("SAPGUI").GetScriptingEngine
                if app.Connections.Count > baseline:
                    conn = app.Connections(app.Connections.Count - 1)
                    break
            except Exception:  # noqa: BLE001 — not registered in the ROT yet
                pass
            time.sleep(1)
        if conn is None:
            raise SapError(
                f"Timed out after {timeout:.0f}s waiting for SAP GUI to open "
                f"(system={system!r}, client={client!r}). Check that SSO completed "
                f"and scripting is enabled (sapgui/user_scripting=TRUE)."
            )

        session = None
        while time.monotonic() < deadline:
            try:
                candidate = conn.Sessions(0)
                if (candidate.Info.User or "").strip():
                    session = candidate
                    break
            except Exception:  # noqa: BLE001 — session still mid-login
                pass
            time.sleep(1)
        if session is None:
            raise SapError(
                f"SAP GUI opened but SSO login did not complete within {timeout:.0f}s "
                f"(system={system!r}, client={client!r})."
            )

        logger.info("launched fresh SAP session: %s (user=%s)", session.Id, session.Info.User)
        inst = cls(session=session, dry_run=False, connection=conn)
        # Wait for the Easy Access Menu to finish rendering before handing back
        # to the caller — SSO completing only means the login handshake is done,
        # not that the initial screen is ready for scripting.
        inst.wait_ready()
        return inst

    def close(self) -> None:
        """Close a session opened by launch(). No-op in dry-run or for attach()ed
        sessions you didn't open yourself (closing someone else's SAP window would
        be surprising)."""
        if self.dry_run or self._connection is None:
            return
        try:
            self._connection.CloseConnection()
            logger.info("closed SAP session")
        except Exception as e:  # noqa: BLE001 — best-effort cleanup, never fail the run on this
            logger.warning("failed to close SAP session: %s", e)

    # ── actions ──────────────────────────────────────────────────────────────
    def start_transaction(self, tcode: str) -> None:
        logger.info("start_transaction(%s)", tcode)
        if self.dry_run:
            return
        try:
            self._session.StartTransaction(tcode)
        except Exception as e:  # noqa: BLE001
            raise SapError(f"StartTransaction({tcode}) failed: {e}") from e
        # Screen transition — wait for the new screen to finish loading.
        self.wait_ready()

    def set_text(self, element_id: str, value: str) -> None:
        logger.info("set_text(%s, %r)", element_id, value)
        if self.dry_run:
            return
        # set_text is a local field write — no server round-trip, no wait needed.
        self._find(element_id).text = value

    def get_text(self, element_id: str) -> str:
        if self.dry_run:
            return ""
        return self._find(element_id).text

    def press(self, element_id: str) -> None:
        """Press a button."""
        logger.info("press(%s)", element_id)
        if self.dry_run:
            return
        self._find(element_id).press()
        # Button presses can navigate to a new screen or trigger server work.
        self.wait_ready()

    def select(self, element_id: str) -> None:
        """Select a menu / radio / checkbox / tab."""
        logger.info("select(%s)", element_id)
        if self.dry_run:
            return
        self._find(element_id).select()
        # Tab/menu selections can trigger a screen repaint or data load.
        self.wait_ready()

    def send_vkey(self, vkey: int, window: str = "wnd[0]") -> None:
        """Send a virtual key to a window. 0=Enter, 8=F8/Execute, 3=Back, 11=Save."""
        logger.info("send_vkey(%d) on %s", vkey, window)
        if self.dry_run:
            return
        self._find(window).sendVKey(vkey)
        # Virtual keys (Enter, Save, F8, Back, …) always go to the server.
        self.wait_ready()

    def status_bar(self) -> dict:
        """Read the status bar — the primary outcome signal in SAP."""
        if self.dry_run:
            return {"type": "", "text": "", "message_id": "", "message_number": ""}
        try:
            bar = self._find("wnd[0]/sbar")
            return {
                "type": getattr(bar, "MessageType", ""),
                "text": getattr(bar, "Text", ""),
                "message_id": getattr(bar, "MessageId", ""),
                "message_number": getattr(bar, "MessageNumber", ""),
            }
        except SapError:
            return {"type": "", "text": "", "message_id": "", "message_number": ""}

    # ── perception ───────────────────────────────────────────────────────────
    def exists(self, element_id: str) -> bool:
        if self.dry_run:
            return True
        try:
            self._session.findById(element_id)
            return True
        except Exception:  # noqa: BLE001
            return False

    def snapshot(self, root_id: str = "wnd[0]", max_depth: int = 6) -> SapElement:
        """
        Walk the element tree under root_id into a serialisable structure.
        This is what gets handed to the model for planning / self-healing.
        """
        if self.dry_run:
            return SapElement(id=root_id, type="GuiMainWindow",
                              text="(dry-run: no live SAP tree)")
        root = self._find(root_id)
        return self._walk(root, max_depth)

    def screenshot_b64(self, window: str = "wnd[0]") -> Optional[str]:
        """
        Capture the SAP window as base64 PNG for vision self-heal.
        Uses the scripting HardCopy API, then reads the file back.
        Returns None in dry-run or on failure (engine then uses text-only heal).
        """
        if self.dry_run:
            return None
        try:
            import base64
            import tempfile
            path = os.path.join(tempfile.gettempdir(), "sap_hardcopy.png")
            self._find(window).hardCopy(path, 1)  # 1 = PNG
            with open(path, "rb") as f:
                return base64.b64encode(f.read()).decode("ascii")
        except Exception as e:  # noqa: BLE001
            logger.warning("screenshot_b64 failed: %s", e)
            return None

    # ── synchronisation ──────────────────────────────────────────────────────
    def wait_ready(self, timeout: float = _BUSY_TIMEOUT,
                   poll_interval: float = _BUSY_POLL) -> None:
        """
        Block until session.Busy is False or timeout expires.

        SAP GUI Scripting's Busy flag is True during any in-flight server
        round-trip or screen transition. Polling it is the only reliable way
        to know the next findById() / text= won't race against an in-progress
        repaint.  Fixed sleeps are either too short (flaky) or too long (slow).
        """
        if self.dry_run or self._session is None:
            return
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if not self._session.Busy:
                    return
            except Exception:  # noqa: BLE001 — COM may be mid-transition; keep polling
                pass
            time.sleep(poll_interval)
        logger.warning("wait_ready: SAP session still busy after %.1fs — continuing anyway",
                       timeout)

    # ── helpers ──────────────────────────────────────────────────────────────
    def _find(self, element_id: str):
        try:
            return self._session.findById(element_id)
        except Exception as e:  # noqa: BLE001
            raise SapError(f"Element not found: {element_id}") from e

    def _walk(self, node, depth: int) -> SapElement:
        el = SapElement(
            id=getattr(node, "Id", ""),
            type=getattr(node, "Type", ""),
            name=getattr(node, "Name", ""),
            text=str(getattr(node, "Text", "") or ""),
            tooltip=str(getattr(node, "Tooltip", "") or ""),
            changeable=bool(getattr(node, "Changeable", True)),
        )
        if depth <= 0:
            return el
        try:
            kids = node.Children
            for i in range(kids.Count):
                el.children.append(self._walk(kids.ElementAt(i), depth - 1))
        except Exception:  # noqa: BLE001 — leaf node or no Children property
            pass
        return el
