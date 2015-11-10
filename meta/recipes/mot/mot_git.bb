SUMMARY = "Sensor data pump agent for MasterOfThings.com"
LICENSE = "BSD-3-Clause"
LIC_FILES_CHKSUM = "file://LICENSE;md5=7d9a83a293368bcc11d0011afb4b33da"

S = "${WORKDIR}/git"
SRCREV = "5ad177e45d4ead274ffa02c996a0f44cdd5f3b0f"
PV = "20151104"
RDEPENDS_${PN} = "python3"

SRC_URI = "\
	git://github.com/jjkivilu/mot.git;protocol=http \
	file://mot \
"

inherit update-rc.d
INITSCRIPT_NAME = "mot"
INITSCRIPT_PARAMS = "defaults 80"

do_configure[noexec] = "1"
do_compile[noexec] = "1"

do_install() {
  install -d ${D}${sysconfdir}/init.d
  install -m 0755 ${WORKDIR}/mot ${D}${sysconfdir}/init.d
  install -d ${D}${bindir}
  install -m 0755 ${WORKDIR}/mot.py ${D}${bindir}
  install -d ${D}${sysconfdir}
  install -m 0644 ${WORKDIR}/mot.conf ${D}${sysconfdir}
  install -d ${D}${localstatedir}/cache
  install -m 0644 ${WORKDIR}/mot.state ${D}${localstatedir}/cache
}

