#!/usr/bin/env python3

import argparse
from pathlib import Path

REPLACEMENTS = {
    "QtWidgets.QSizePolicy.MinimumExpanding": "QtWidgets.QSizePolicy.Policy.MinimumExpanding",
    "QtWidgets.QSizePolicy.Minimum": "QtWidgets.QSizePolicy.Policy.Minimum",
    "QtWidgets.QSizePolicy.Fixed": "QtWidgets.QSizePolicy.Policy.Fixed",
    "QtWidgets.QSizePolicy.Expanding": "QtWidgets.QSizePolicy.Policy.Expanding",
    "QtWidgets.QSizePolicy.Preferred": "QtWidgets.QSizePolicy.Policy.Preferred",
    "QtWidgets.QSizePolicy.Maximum": "QtWidgets.QSizePolicy.Policy.Maximum",
    "QtWidgets.QSizePolicy.Ignored": "QtWidgets.QSizePolicy.Policy.Ignored",
}

REPLACEMENTS.update({
    "QtCore.Qt.AlignTop": "QtCore.Qt.AlignmentFlag.AlignTop",
    "QtCore.Qt.AlignBottom": "QtCore.Qt.AlignmentFlag.AlignBottom",
    "QtCore.Qt.AlignLeft": "QtCore.Qt.AlignmentFlag.AlignLeft",
    "QtCore.Qt.AlignRight": "QtCore.Qt.AlignmentFlag.AlignRight",
    "QtCore.Qt.AlignCenter": "QtCore.Qt.AlignmentFlag.AlignCenter",
    "QtCore.Qt.AlignVCenter": "QtCore.Qt.AlignmentFlag.AlignVCenter",
    "QtCore.Qt.AlignHCenter": "QtCore.Qt.AlignmentFlag.AlignHCenter",
    "QtCore.Qt.AlignJustify": "QtCore.Qt.AlignmentFlag.AlignJustify",
    "QtCore.Qt.AlignAbsolute": "QtCore.Qt.AlignmentFlag.AlignAbsolute",
})

REPLACEMENTS.update({
    "QtCore.Qt.UserRole": "QtCore.Qt.ItemDataRole.UserRole",
    "QtCore.Qt.DisplayRole": "QtCore.Qt.ItemDataRole.DisplayRole",
    "QtCore.Qt.DecorationRole": "QtCore.Qt.ItemDataRole.DecorationRole",
    "QtCore.Qt.EditRole": "QtCore.Qt.ItemDataRole.EditRole",
    "QtCore.Qt.ToolTipRole": "QtCore.Qt.ItemDataRole.ToolTipRole",
    "QtCore.Qt.StatusTipRole": "QtCore.Qt.ItemDataRole.StatusTipRole",
    "QtCore.Qt.WhatsThisRole": "QtCore.Qt.ItemDataRole.WhatsThisRole",
    "QtCore.Qt.CheckStateRole": "QtCore.Qt.ItemDataRole.CheckStateRole",
    "QtCore.Qt.SizeHintRole": "QtCore.Qt.ItemDataRole.SizeHintRole",
})

REPLACEMENTS.update({
    "QtWidgets.QDialogButtonBox.Ok": "QtWidgets.QDialogButtonBox.StandardButton.Ok",
    "QtWidgets.QDialogButtonBox.Open": "QtWidgets.QDialogButtonBox.StandardButton.Open",
    "QtWidgets.QDialogButtonBox.Save": "QtWidgets.QDialogButtonBox.StandardButton.Save",
    "QtWidgets.QDialogButtonBox.Cancel": "QtWidgets.QDialogButtonBox.StandardButton.Cancel",
    "QtWidgets.QDialogButtonBox.Close": "QtWidgets.QDialogButtonBox.StandardButton.Close",
    "QtWidgets.QDialogButtonBox.Discard": "QtWidgets.QDialogButtonBox.StandardButton.Discard",
    "QtWidgets.QDialogButtonBox.Apply": "QtWidgets.QDialogButtonBox.StandardButton.Apply",
    "QtWidgets.QDialogButtonBox.Reset": "QtWidgets.QDialogButtonBox.StandardButton.Reset",
    "QtWidgets.QDialogButtonBox.RestoreDefaults": "QtWidgets.QDialogButtonBox.StandardButton.RestoreDefaults",
    "QtWidgets.QDialogButtonBox.Help": "QtWidgets.QDialogButtonBox.StandardButton.Help",
    "QtWidgets.QDialogButtonBox.SaveAll": "QtWidgets.QDialogButtonBox.StandardButton.SaveAll",
    "QtWidgets.QDialogButtonBox.Yes": "QtWidgets.QDialogButtonBox.StandardButton.Yes",
    "QtWidgets.QDialogButtonBox.YesToAll": "QtWidgets.QDialogButtonBox.StandardButton.YesToAll",
    "QtWidgets.QDialogButtonBox.No": "QtWidgets.QDialogButtonBox.StandardButton.No",
    "QtWidgets.QDialogButtonBox.NoToAll": "QtWidgets.QDialogButtonBox.StandardButton.NoToAll",
    "QtWidgets.QDialogButtonBox.Abort": "QtWidgets.QDialogButtonBox.StandardButton.Abort",
    "QtWidgets.QDialogButtonBox.Retry": "QtWidgets.QDialogButtonBox.StandardButton.Retry",
    "QtWidgets.QDialogButtonBox.Ignore": "QtWidgets.QDialogButtonBox.StandardButton.Ignore",
})

REPLACEMENTS.update({
    "QtNetwork.QNetworkRequest.HttpStatusCodeAttribute":
        "QtNetwork.QNetworkRequest.Attribute.HttpStatusCodeAttribute",

    "QtNetwork.QNetworkRequest.HttpReasonPhraseAttribute":
        "QtNetwork.QNetworkRequest.Attribute.HttpReasonPhraseAttribute",

    "QtNetwork.QNetworkRequest.RedirectionTargetAttribute":
        "QtNetwork.QNetworkRequest.Attribute.RedirectionTargetAttribute",

    "QtNetwork.QNetworkRequest.ConnectionEncryptedAttribute":
        "QtNetwork.QNetworkRequest.Attribute.ConnectionEncryptedAttribute",

    "QtNetwork.QNetworkRequest.CacheLoadControlAttribute":
        "QtNetwork.QNetworkRequest.Attribute.CacheLoadControlAttribute",

    "QtNetwork.QNetworkRequest.CacheSaveControlAttribute":
        "QtNetwork.QNetworkRequest.Attribute.CacheSaveControlAttribute",

    "QtNetwork.QNetworkRequest.SourceIsFromCacheAttribute":
        "QtNetwork.QNetworkRequest.Attribute.SourceIsFromCacheAttribute",
})

REPLACEMENTS.update({
    "QtNetwork.QNetworkReply.NoError":
        "QtNetwork.QNetworkReply.NetworkError.NoError",

    "QtNetwork.QNetworkReply.ConnectionRefusedError":
        "QtNetwork.QNetworkReply.NetworkError.ConnectionRefusedError",

    "QtNetwork.QNetworkReply.RemoteHostClosedError":
        "QtNetwork.QNetworkReply.NetworkError.RemoteHostClosedError",

    "QtNetwork.QNetworkReply.HostNotFoundError":
        "QtNetwork.QNetworkReply.NetworkError.HostNotFoundError",

    "QtNetwork.QNetworkReply.TimeoutError":
        "QtNetwork.QNetworkReply.NetworkError.TimeoutError",

    "QtNetwork.QNetworkReply.OperationCanceledError":
        "QtNetwork.QNetworkReply.NetworkError.OperationCanceledError",

    "QtNetwork.QNetworkReply.SslHandshakeFailedError":
        "QtNetwork.QNetworkReply.NetworkError.SslHandshakeFailedError",

    "QtNetwork.QNetworkReply.TemporaryNetworkFailureError":
        "QtNetwork.QNetworkReply.NetworkError.TemporaryNetworkFailureError",

    "QtNetwork.QNetworkReply.ProxyConnectionRefusedError":
        "QtNetwork.QNetworkReply.NetworkError.ProxyConnectionRefusedError",

    "QtNetwork.QNetworkReply.ContentAccessDenied":
        "QtNetwork.QNetworkReply.NetworkError.ContentAccessDenied",

    "QtNetwork.QNetworkReply.ContentOperationNotPermittedError":
        "QtNetwork.QNetworkReply.NetworkError.ContentOperationNotPermittedError",

    "QtNetwork.QNetworkReply.ContentNotFoundError":
        "QtNetwork.QNetworkReply.NetworkError.ContentNotFoundError",

    "QtNetwork.QNetworkReply.AuthenticationRequiredError":
        "QtNetwork.QNetworkReply.NetworkError.AuthenticationRequiredError",
})

REPLACEMENTS.update({
    "QtCore.Qt.ScrollBarAlwaysOff":
        "QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff",
    "QtCore.Qt.ScrollBarAlwaysOn":
        "QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOn",
    "QtCore.Qt.ScrollBarAsNeeded":
        "QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded",
})

REPLACEMENTS.update({
    "QtNetwork.QNetworkReply.ProxyConnectionRefusedError":
        "QtNetwork.QNetworkReply.NetworkError.ProxyConnectionRefusedError",

    "QtNetwork.QNetworkReply.ProxyConnectionClosedError":
        "QtNetwork.QNetworkReply.NetworkError.ProxyConnectionClosedError",

    "QtNetwork.QNetworkReply.ProxyNotFoundError":
        "QtNetwork.QNetworkReply.NetworkError.ProxyNotFoundError",

    "QtNetwork.QNetworkReply.ProxyTimeoutError":
        "QtNetwork.QNetworkReply.NetworkError.ProxyTimeoutError",

    "QtNetwork.QNetworkReply.ProxyAuthenticationRequiredError":
        "QtNetwork.QNetworkReply.NetworkError.ProxyAuthenticationRequiredError",
})

def should_skip(path: Path) -> bool:
    parts = set(path.parts)
    return bool(parts & {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        "build",
        "dist",
    })


def patch_file(path: Path, dry_run: bool) -> bool:
    text = path.read_text(encoding="utf-8")
    new_text = text

    for old, new in REPLACEMENTS.items():
        new_text = new_text.replace(old, new)

    if new_text == text:
        return False

    if not dry_run:
        path.write_text(new_text, encoding="utf-8")

    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replace PyQt5-style QSizePolicy enum access with PyQt6-style enum access."
    )
    parser.add_argument(
        "root",
        help="Root folder to recursively patch.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show files that would be changed without modifying them.",
    )

    args = parser.parse_args()

    root = Path(args.root).resolve()

    if not root.exists():
        raise SystemExit(f"Root folder does not exist: {root}")

    if not root.is_dir():
        raise SystemExit(f"Root path is not a directory: {root}")

    changed = []

    for path in root.rglob("*.py"):
        if should_skip(path):
            continue

        try:
            if patch_file(path, args.dry_run):
                changed.append(path)
        except UnicodeDecodeError:
            print(f"Skipped non-UTF-8 file: {path}")

    if changed:
        action = "Would update" if args.dry_run else "Updated"
        print(f"{action} {len(changed)} file(s):")
        for path in changed:
            print(f"  {path}")
    else:
        print("No files changed.")


if __name__ == "__main__":
    main()
