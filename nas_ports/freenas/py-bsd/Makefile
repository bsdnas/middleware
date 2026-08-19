# $FreeBSD$

PORTNAME=	bsd
PORTVERSION=	${PRODUCT_VERSION:C/\-.*//:C/\_.*//}
PKGNAMEPREFIX=	${PYTHON_PKGNAMEPREFIX}

CATEGORIES=	freenas
VALID_CATEGORIES+= freenas

MAINTAINER=	richard@kojedz.in
COMMENT=	Python wrappers for various BSD interfaces

# freenas/py-bsd, LICENSE file in the upstream repository
LICENSE=	BSD3CLAUSE

EXTRACT_ONLY=

WRKSRC=		/usr/nas_source/py-bsd
LIB_DEPENDS=	libcdialog.so:devel/cdialog

USES=		python
USE_PYTHON=	autoplist cython distutils

checksum fetch:
	${ECHO_CMD} ${.TARGET} not needed because building direct

.include <bsd.port.mk>
