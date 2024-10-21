# $FreeBSD$

PORTNAME=	kmip
PORTVERSION=	0.10.0
CATEGORIES=	truenas devel python
VALID_CATEGORIES+= truenas
PKGNAMEPREFIX=	${PYTHON_PKGNAMEPREFIX}

MAINTAINER=	waqar@ixsystems.com
COMMENT=	Python implementation of KMIP protocol

LICENSE=	APACHE20
LICENSE_FILE=	${WRKSRC}/LICENSE.txt

RUN_DEPENDS=	${PYTHON_PKGNAMEPREFIX}requests>=2.20:www/py-requests@${PY_FLAVOR} \
		${PYTHON_PKGNAMEPREFIX}cryptography>0:security/py-cryptography@${PY_FLAVOR} \
		${PYTHON_PKGNAMEPREFIX}sqlalchemy14>0:databases/py-sqlalchemy14@${PY_FLAVOR} \
		${PYTHON_PKGNAMEPREFIX}six>=1.8.0:devel/py-six@${PY_FLAVOR}

USE_GITHUB=	yes
GH_ACCOUNT=	OpenKMIP
GH_PROJECT=	PyKMIP
GH_TAGNAME=	6cd44b572b0ca55adf01a8a12078b2284602e64c

USES=		python:3.7+
USE_PYTHON=	autoplist concurrent distutils
NO_ARCH=	yes

.include <bsd.port.mk>
