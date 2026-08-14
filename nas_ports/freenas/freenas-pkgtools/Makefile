# $FreeBSD$

PORTNAME=	freenas-pkgtools
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
COMMENT=	BSDnas packaging, update and installation tools

USES=		python

EXTRACT_ONLY=
WRKSRC=/usr/nas_source/freenas-pkgtools

# no checksum, we just used git!
checksum fetch:
	${ECHO_CMD} ${.TARGET} not needed because building direct

ALL_TARGET=obj all

MAKE_JOBS_UNSAFE=yes

post-install:
	${PYTHON_CMD} -m compileall ${STAGEDIR}${PREFIX}/lib/freenasOS
	(cd ${STAGEDIR}${PREFIX}/lib/freenasOS; ${FIND} . -type f \
		| ${SED} -e 's,^\./,,g' \
		| ${AWK} '{print length, $$0}' | ${SORT} -rn \
		| ${AWK} '{print "lib/freenasOS/"$$2 }' >> ${TMPPLIST})

.include <bsd.port.mk>
