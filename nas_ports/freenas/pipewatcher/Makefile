# $FreeBSD$

PORTNAME=	pipewatcher
PORTVERSION=	${PRODUCT_VERSION:C/\-.*//:C/\_.*//}
# Ревизия привязана к ревизии исходников. Без этого имя пакета не меняется
# при правках нашего дерева, poudriere считает пакет актуальным и правки
# молча не доезжают до образа: так корневой сертификат iX оставался в
# системе уже после того, как был убран из списка файлов.
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
