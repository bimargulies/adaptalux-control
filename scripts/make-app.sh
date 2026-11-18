#!/bin/sh
# Build Adaptalux.app: a small launcher that opens the window from Finder or the Dock.
#
# The app runs the code in this checkout, so build it on each Mac, after `uv sync --extra gui`,
# and rebuild it if you move the checkout.
#
# Usage: scripts/make-app.sh [destination folder]   (default: ~/Applications)

set -eu

repo=$(cd "$(dirname "$0")/.." && pwd)
dest=${1:-"$HOME/Applications"}
app="$dest/Adaptalux.app"
python="$repo/.venv/bin/python"

if ! "$python" -c "import adaptalux_control.gui, PySide6, qasync" 2>/dev/null; then
    echo "The GUI is not installed in $repo/.venv. Run: uv sync --extra gui" >&2
    exit 1
fi

mkdir -p "$dest"
rm -rf "$app"
mkdir -p "$app/Contents/MacOS"

# The launcher replaces itself with Python (exec), so the window runs as this app: one Dock icon,
# and macOS asks about Bluetooth for "Adaptalux" instead of a terminal.
cat > "$app/Contents/MacOS/adaptalux" <<EOF
#!/bin/sh
log="\$HOME/Library/Logs/adaptalux.log"
echo "--- \$(date) starting" >> "\$log"
cd "$repo"
exec "$python" -c "from adaptalux_control.gui import main; main()" >> "\$log" 2>&1
EOF
chmod +x "$app/Contents/MacOS/adaptalux"

# NSBluetoothAlwaysUsageDescription is required: without it macOS kills the app when it uses Bluetooth.
cat > "$app/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>Adaptalux</string>
    <key>CFBundleDisplayName</key>
    <string>Adaptalux</string>
    <key>CFBundleIdentifier</key>
    <string>io.github.bimargulies.adaptalux-control</string>
    <key>CFBundleExecutable</key>
    <string>adaptalux</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleVersion</key>
    <string>0.1.0</string>
    <key>CFBundleShortVersionString</key>
    <string>0.1.0</string>
    <key>LSMinimumSystemVersion</key>
    <string>13.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>NSBluetoothAlwaysUsageDescription</key>
    <string>Adaptalux uses Bluetooth to control your Adaptalux Control Pods.</string>
</dict>
</plist>
EOF

# Ad-hoc signature: enough for an app built on this Mac (it is not quarantined, so Gatekeeper does not check it).
codesign --force --sign - "$app"

# Tell Finder and Launchpad about it.
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$app" || true

echo "Built $app"
echo "Errors go to ~/Library/Logs/adaptalux.log"
