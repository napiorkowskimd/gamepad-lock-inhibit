# Maintainer: Michał Napiórkowski
pkgname=gamepad-lock-inhibit
pkgver=0.0.1
pkgrel=1
pkgdesc="Service that prevents screensaver when gamepad is actively used"
arch=('any')
url="https://github.com/napiorkowskimd/gamepad-lock-inhibit"
license=('MIT')
depends=('python>3.8.0' 'python-pyudev' 'python-pydbus' 'python-evdev')
source=('gamepad-lock-inhibit.py' 'gamepad-lock-inhibit.service')

md5sums=('ae9ac9dbb29e0af57ec5389454b48ec1'
         '1225d1685042a21aac6388757f7895bc')


package() {
    install -d $pkgdir/usr/bin/
    install -d $pkgdir/usr/lib/systemd/system/
    install gamepad-lock-inhibit.py $pkgdir/usr/bin/gamepad-lock-inhibit.py
    install gamepad-lock-inhibit.service $pkgdir/usr/lib/systemd/system/gamepad-lock-inhibit.service
}