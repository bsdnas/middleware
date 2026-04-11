PORTNAME=	netif
PORTVERSION=	1.0.20220211
PORTREVISION=	1
CATEGORIES=	freenas net python
VALID_CATEGORIES+= freenas
PKGNAMEPREFIX=	${PYTHON_PKGNAMEPREFIX}

MAINTAINER=	bofh@FreeBSD.org
COMMENT=	Python network configuration library for FreeBSD
WWW=		https://github.com/freenas/py-netif

LICENSE=	BSD2CLAUSE

RUN_DEPENDS=	${PYTHON_PKGNAMEPREFIX}bsd>0:freenas/py-bsd@${PY_FLAVOR}

USES=		python
USE_GITHUB=	yes
GH_ACCOUNT=	dravanet
GH_PROJECT=	py-netif
GH_TAGNAME=	2f309bc
USE_PYTHON=	autoplist cython distutils

HAS_CONFIGURE=	yes

post-install:
	@${STRIP_CMD} ${STAGEDIR}${PYTHONPREFIX_SITELIBDIR}/netif*.so

.include <bsd.port.mk>
