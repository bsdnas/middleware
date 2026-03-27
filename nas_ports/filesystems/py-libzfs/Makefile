# Created by: William Grzybowski <wg@FreeBSD.org>
# $FreeBSD$

PORTNAME=	libzfs
PORTVERSION=	25.04.1.20251125
CATEGORIES=	filesystems python
PKGNAMEPREFIX=	${PYTHON_PKGNAMEPREFIX}

MAINTAINER=	wg@FreeBSD.org
COMMENT=	Python libzfs bindings

LICENSE=	BSD2CLAUSE

RUN_DEPENDS=	${PY_ENUM34}

USE_GITHUB=     yes
GH_ACCOUNT=	truenas
GH_PROJECT=	py-libzfs
GH_TAGNAME=	33e01e9f8574e90c44c71a3ab62726540ca12c01

HAS_CONFIGURE=	yes
USES=		compiler:c11 python
USE_PYTHON=	autoplist distutils cython

CONFIGURE_ENV=	freebsd_src=${SRC_BASE}
MAKE_ENV=	freebsd_src=${SRC_BASE}

# Py-libzfs needs libzfs to be built
.if !exists(/sbin/zpool)
BUILD_DEPENDS+=        openzfs>=0:filesystems/openzfs
RUN_DEPENDS+=  openzfs>=0:filesystems/openzfs
.endif

.include <bsd.port.options.mk>

.if !exists(${SRC_BASE}/sys/Makefile)
IGNORE=	requires kernel source files in ${SRC_BASE}
.endif

.include <bsd.port.mk>
