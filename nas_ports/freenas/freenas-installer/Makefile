# $FreeBSD$

PORTNAME=	freenas-installer
PORTVERSION=	${PRODUCT_VERSION:C/\-.*//:C/\_.*//}
# Without a revision the package name is always freenas-installer-15 and
# poudriere considers it forever up to date: changes to install.sh silently do
# not reach the image until the package is removed by hand. REVISION comes from
# ports-installer.pyd and equals the timestamp of the last middleware commit,
# the same way it is done for freenas-webui.
PORTREVISION=	${REVISION}

CATEGORIES=	freenas
VALID_CATEGORIES+=	freenas

MAINTAINER=	dev@ixsystems.com
COMMENT=	BSDnas installer

RUN_DEPENDS=	dmidecode>0:sysutils/dmidecode

USE_XZ=		yes

NO_BUILD=	yes

PREFIX=/

# explicitly set this for the port build
PLIST_SUB=	MACHINE_ARCH=${MACHINE_ARCH}

EXTRACT_ONLY=
WRKSRC=/usr/nas_source

# no checksum, we just used git!
checksum fetch:
	${ECHO_CMD} ${.TARGET} not needed because building direct

pre-clean:
	@

ALL_TARGET=obj all

MAKE_JOBS_UNSAFE=yes

.include <bsd.port.pre.mk>

do-install:
	mkdir -p ${STAGEDIR}/${PREFIX}/pre-install
	${INSTALL_SCRIPT} ${WRKSRC}/freenas-installer/bin/install_worker.sh ${STAGEDIR}/${PREFIX}/bin/install_worker.sh
	${INSTALL_SCRIPT} ${WRKSRC}/freenas-installer/bin/install_worker2.sh ${STAGEDIR}/${PREFIX}/bin/install_worker2.sh
	${INSTALL_SCRIPT} ${WRKSRC}/freenas-installer/etc/install.sh ${STAGEDIR}/${PREFIX}/etc/install.sh
	${INSTALL_SCRIPT} ${WRKSRC}/freenas-installer/etc/rc ${STAGEDIR}/${PREFIX}/etc/rc
	${INSTALL_SCRIPT} ${WRKSRC}/freenas-installer/lib/functions.sh ${STAGEDIR}/${PREFIX}/lib/functions.sh
	cp -a ${WRKSRC}/freenas-installer/pre-install/ ${STAGEDIR}/${PREFIX}/pre-install/

.include <bsd.port.post.mk>
