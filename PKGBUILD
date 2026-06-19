# Maintainer: dutchteaa <aiden dot vonk07 at gmail dot com>
pkgname=tea-clipper
pkgver=0.1.0
pkgrel=1
pkgdesc="Medal-style instant-replay game clipper for Linux/Wayland (KDE)"
arch=('any')
url="https://github.com/dutchteaa/tea-clipper"
license=('MIT')
depends=(
  'python'
  'python-gobject'
  'python-tomli-w'
  'gstreamer'
  'gst-plugins-base'
  'gst-plugins-good'   # splitmuxsink + matroskamux (rolling buffer) -- hard requirement
  'gst-plugin-pipewire'
  'gst-plugin-va'      # VAAPI encode on AMD/Intel (vah264enc etc.)
  'gst-plugins-ugly'   # x264enc software-encode fallback
  'gst-plugins-bad'    # webrtcdsp mic noise suppression
  'pyside6'
  'ffmpeg'             # lossless clip stitching (-c copy)
  'libpulse'           # provides pactl for audio-device discovery
  'xdg-desktop-portal' # ScreenCast + GlobalShortcuts portal frontend (D-Bus) -- hard requirement
)
optdepends=(
  'xdg-desktop-portal-kde: portal backend for KDE Plasma (other DEs: -gnome, -wlr, ...)'
)
makedepends=('python-build' 'python-installer' 'python-wheel' 'python-setuptools')
source=("$pkgname-$pkgver.tar.gz::$url/archive/refs/tags/v$pkgver.tar.gz")
sha256sums=('5c913f0ad943e92301862ea9ca988ce4c8cd5ff0f7ed01c26e8d79473d131435')

build() {
  cd "$pkgname-$pkgver"
  python -m build --wheel --no-isolation
}

package() {
  cd "$pkgname-$pkgver"
  python -m installer --destdir="$pkgdir" dist/*.whl

  install -Dm644 tea-clipper.desktop \
    "$pkgdir/usr/share/applications/tea-clipper.desktop"
  install -Dm644 assets/tea-clipper.svg \
    "$pkgdir/usr/share/icons/hicolor/scalable/apps/tea-clipper.svg"
  install -Dm644 LICENSE \
    "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}
