PORTNAME=	zfssend
PORTVERSION=	0.0.1

CATEGORIES=	truenas
VALID_CATEGORIES+=	truenas

MAINTAINER=	richard@kojedz.in
COMMENT=	zfs send wrapper command

EXTRACT_ONLY=

BUILD_DEPENDS=	go:lang/go
WRKSRC=		/usr/nas_source/zfssend

checksum fetch:
	echo ${.TARGET} not needed because building direct

.include <bsd.port.mk>
