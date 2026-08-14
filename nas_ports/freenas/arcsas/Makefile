#
# $FreeBSD$
# $Id$
#

PORTNAME=       arcsas
PORTVERSION=    1.0
# The revision is tied to the source tree revision. Without it the package name
# does not change when our tree is edited, poudriere considers the package up to
# date and the changes silently never reach the image: that is how the iX root
# certificate stayed in the system long after it had been removed from the file
# list.
PORTREVISION=	${REVISION}

CATEGORIES=     freenas
VALID_CATEGORIES+=	freenas

MAINTAINER=     dev@ixsystems.com
COMMENT=        Driver for Areca 13xx SAS HBAs

USE_XZ=		yes

PREFIX=/

# explicitly set this for the port build
FREEBSD_SRCTOP=/usr/src
PLIST_SUB=	MACHINE_ARCH=${MACHINE_ARCH}

EXTRACT_ONLY=
WRKSRC=/usr/nas_source

# no checksum, we just used git!
 #extract:
checksum fetch:
	echo ${.TARGET} not needed because building direct

pre-clean:
	@

ALL_TARGET=obj all

MAKE_JOBS_UNSAFE=yes

do-build:
	@

do-install:
	mkdir -p ${STAGEDIR}${PREFIX}/boot/modules
	${INSTALL_DATA} ${WRKSRC}/kernel_modules/arcsas_${MACHINE_ARCH}.ko ${STAGEDIR}${PREFIX}/boot/modules/arcsas.ko

.include <bsd.port.mk>
