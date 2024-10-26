PORTNAME=	netsnmpagent
PORTVERSION=	0.6.0
PORTREVISION=	1
CATEGORIES=	net python
PKGNAMEPREFIX=	${PYTHON_PKGNAMEPREFIX}

MAINTAINER=	vladimirv@ixsystems.com
COMMENT=	Python module that facilitates writing Net-SNMP subagents in Python
WWW=		https://pypi.org/project/netsnmpagent/

LICENSE=	LGPL3
LICENSE_FILE=	${WRKSRC}/LICENSE

USES=		python
USE_PYTHON=	autoplist concurrent distutils
USE_GITHUB=	yes
GH_ACCOUNT=	rkojedzinszky
GH_PROJECT=	python-netsnmpagent
GH_TAGNAME=	31e8d0711c

.include <bsd.port.pre.mk>

pre-configure:
	# Copied from Makefile
	sed 's/@NETSNMPAGENT_VERSION@/$(PKGVERSION:C/_/-/)/' $(WRKSRC)/setup.py.in >$(WRKSRC)/setup.py
	chmod u+x $(WRKSRC)/setup.py

.include <bsd.port.post.mk>
