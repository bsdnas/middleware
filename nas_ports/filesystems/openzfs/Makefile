PORTNAME=	openzfs
PORTVERSION=	2.3.6
DISTVERSIONPREFIX=	v
CATEGORIES=	filesystems

MAINTAINER=	richard@kojedz.in
COMMENT=	OpenZFS userland for FreeBSD

LICENSE=	CDDL

BROKEN_aarch64=	invokes x86 assembler
BROKEN_riscv64=	fails to compile: btree_test.c:462:49: result of comparison of constant -1 with expression of type 'char' is always true

RUN_DEPENDS=	openzfs-kmod>=0:filesystems/openzfs-kmod

USES+=		autoreconf:build cpe libtool gmake gettext-runtime python:3.3+,build shebangfix

GNU_CONFIGURE=	yes
CONFIGURE_ARGS=	--prefix=${PREFIX} --with-config="user"

OPTIONS_DEFINE=	DEBUG PYTHON TESTS
PYTHON_DESC=	Build the pyzfs library, arc_summary, arcstat, and dbufstat utilities
TESTS_DESC=	Install the ZFS Test Suite
OPTIONS_SUB=	yes

USE_GITHUB=	yes
GH_ACCOUNT=	dravanet
GH_PROJECT=	openzfs-zfs
GH_TAGNAME=	aa9bb881dc

.include <bsd.port.pre.mk>

.if ${OSVERSION} >= 1300000 && ${OSVERSION} < 1300013
IGNORE=	needs FreeBSD 12/13 with AES-CCM support
.endif

.if ${PORT_OPTIONS:MDEBUG}
CONFIGURE_ARGS+=	--enable-debug --enable-debuginfo
.endif

.if ${PORT_OPTIONS:MPYTHON}
CONFIGURE_ARGS+=	--with-python=${PYTHON_VER}
BUILD_DEPENDS+=	${PYTHON_PKGNAMEPREFIX}setuptools>0:devel/py-setuptools@${PY_FLAVOR}
BUILD_DEPENDS+=	${PYTHON_PKGNAMEPREFIX}packaging>0:devel/py-packaging@${PY_FLAVOR}
BUILD_DEPENDS+=	${PYTHON_PKGNAMEPREFIX}cffi>0:devel/py-cffi@${PY_FLAVOR}
RUN_DEPENDS+=	${PYTHON_PKGNAMEPREFIX}cffi>0:devel/py-cffi@${PY_FLAVOR}
RUN_DEPENDS+=	${PYTHON_PKGNAMEPREFIX}sysctl>0:devel/py-sysctl@${PY_FLAVOR}
.else
CONFIGURE_ARGS+=	--without-python
.endif

pre-configure:
	cd ${WRKSRC} && ./autogen.sh

post-install:
	cd ${STAGEDIR}${PREFIX} && \
		${FIND} * -type f -o -type l | \
		${SED} -E -e '/__pycache__/d' -e '/\.l?a$$/d' \
		-e '/share\/man\/man[0-9]\/.*\.[0-9]$$/s/$$/.gz/' | ${SORT} > ${TMPPLIST}
.if !${PORT_OPTIONS:MTEST}
	${REINPLACE_CMD} -E -e '/^share\/zfs\/compatibility.d\//{p;d;}' -e '/^share\/zfs\//d' \
		-e '/^s?bin\/.*test$$/d' -e '/^share\/man\/.*test/d' ${TMPPLIST}
.endif

.include <bsd.port.post.mk>
