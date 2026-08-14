# $FreeBSD$

PORTNAME=	pipewatcher
PORTVERSION=	${PRODUCT_VERSION:C/\-.*//:C/\_.*//}
# The revision is tied to the source tree revision. Without it the package name
# does not change when our tree is edited, poudriere considers the package up to
# date and the changes silently never reach the image: that is how the iX root
# certificate stayed in the system long after it had been removed from the file
# list.
PORTREVISION=	${REVISION}

CATEGORIES=	freenas
VALID_CATEGORIES+=	freenas

MAINTAINER=	dev@ixsystems.com
COMMENT=	Pipe watcher to be used in replication

EXTRACT_ONLY=
WRKSRC=/usr/nas_source/pipewatcher

# no checksum, we just used git!
checksum fetch:
	echo ${.TARGET} not needed because building direct

pre-clean:
	@

do-build:
	cd ${WRKSRC} && ${CC} pipewatcher.c -o pipewatcher

do-install:
	mkdir -p ${STAGEDIR}${PREFIX}/bin
	${INSTALL_PROGRAM} ${WRKSRC}/pipewatcher ${STAGEDIR}${PREFIX}/bin/

.include <bsd.port.mk>
