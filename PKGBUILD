# Maintainer: dutchteaa <aiden.vonk07@gmail.com>
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
  'pyside6'
  'ffmpeg'             # lossless clip stitching (-c copy)
  'libpulse'           # provides pactl for audio-device discovery
)
optdepends=(
  'xdg-desktop-portal-kde: ScreenCast + GlobalShortcuts portal backend for KDE Plasma'
)
makedepends=('python-build' 'python-installer' 'python-wheel' 'python-setuptools')
source=("$pkgname-$pkgver.tar.gz::$url/archive/refs/tags/v$pkgver.tar.gz")
sha256sums=('SKIP')

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
