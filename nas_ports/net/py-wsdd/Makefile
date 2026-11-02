# Overlay of net/py-wsdd from the FreeBSD 2026Q2 ports branch. The only
# change is "-f" in the daemon(8) arguments of the rc script
# (files/patch-etc_rc.d_wsdd.freebsd). Without it the daemon supervisor
# keeps the caller's stdout and stderr open, so anything that reads the
# output of "service wsdd start" (the middleware does) waits until wsdd
# exits. With -f those descriptors go to /dev/null; wsdd's own output still
# reaches syslog through -S. The change should go upstream; drop this
# overlay once the ports branch carries it.

PORTNAME=	wsdd
DISTVERSIONPREFIX=	v
DISTVERSION=	0.9
PORTREVISION=	2
CATEGORIES=	net python
PKGNAMEPREFIX=	${PYTHON_PKGNAMEPREFIX}

MAINTAINER=	hiroo.ono+freebsd@gmail.com
COMMENT=	Web Service Discovery (WSD) host daemon for Samba
WWW=		https://github.com/christgau/wsdd

LICENSE=	MIT
LICENSE_FILE=	${WRKSRC}/LICENSE

USES=		python:run shebangfix
USE_GITHUB=	yes
GH_ACCOUNT=	christgau
SHEBANG_FILES=	src/${PORTNAME}.py
NO_ARCH=	yes
NO_BUILD=	yes

USERS=		_wsdd
GROUPS=		_wsdd

PLIST_FILES=	bin/${PORTNAME} \
		etc/rc.d/${PORTNAME} \
		share/man/man8/${PORTNAME}.8.gz
SUB_FILES=	pkg-message

post-patch:
	${REINPLACE_CMD} \
		-e 's|%%PYTHON_CMD%%|${PYTHON_CMD}|' \
		-e 's|%%LOCALBASE%%|${LOCALBASE}|' \
		${WRKSRC}/etc/rc.d/${PORTNAME}.freebsd

do-install:
	${INSTALL_SCRIPT} ${WRKSRC}/src/${PORTNAME}.py \
		${STAGEDIR}${PREFIX}/bin/${PORTNAME}
	@${MKDIR} ${STAGEDIR}${PREFIX}/etc/rc.d
	${INSTALL_SCRIPT} ${WRKSRC}/etc/rc.d/${PORTNAME}.freebsd \
		${STAGEDIR}${PREFIX}/etc/rc.d/${PORTNAME}
	${INSTALL_MAN} ${WRKSRC}/man/${PORTNAME}.8 \
		${STAGEDIR}${PREFIX}/share/man/man8/

.include <bsd.port.mk>
