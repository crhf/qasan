#!/usr/bin/env python3

import os
import sys
import shutil
import platform
import argparse
try:
    import lief
except ImportError:
    print("ERROR: lief not installed.")
    print("   $ pip3 install lief --user")
    print("")
    exit(1)

DESCR = """QEMU-AddressSanitizer Builder
Copyright (C) 2019 Andrea Fioraldi <andreafioraldi@gmail.com>
"""

EPILOG="""Note that the ASan DSO must refer to the host arch in a coherent way
with TARGET_BITS. For example, if the target is arm32 you have to provide the
i386 ASan DSO, if teh target if x86_64 you have to provide the x86_64 DSO.
As example, on Ubuntu 18.04, it is:
/usr/lib/llvm-8/lib/clang/8.0.0/lib/linux/libclang_rt.asan-x86_64.so

"""

ARCHS = {
  "x86_64": "x86_64",
  "amd64": "x86_64",
  "x86": "i386",
  "i386": "i386",
  "arm": "arm",
  "arm64": "aarch64",
  "aarch64": "aarch64",
  #"mips": "mips",
  "mips64": "mips64",
  #"mipsel": "mipsel",
  "mips64el": "mips64el",
}

ARCHS_32 = ["i386", "arm", "mips", "mipsel"]
ARCHS_CROSS = list(set(ARCHS.values()))
ARCHS_CROSS.remove("i386")
ARCHS_CROSS.remove("x86_64")

dir_path = os.path.dirname(os.path.realpath(__file__))

opt = argparse.ArgumentParser(description=DESCR, epilog=EPILOG, formatter_class=argparse.RawTextHelpFormatter)
opt.add_argument("--arch", help="Set target architecture (default x86_64)", action='store', default="x86_64")
opt.add_argument('--asan-dso', help="Path to ASan DSO", action='store', required=("--clean" not in sys.argv))
opt.add_argument("--clean", help="Clean builded files", action='store_true')
opt.add_argument("--cc", help="C compiler (default clang-8)", action='store', default="clang-8")
opt.add_argument("--cxx", help="C++ compiler (default clang++-8)", action='store', default="clang++-8")
opt.add_argument("--cross", help="Cross C compiler for libqasan", action='store')

args = opt.parse_args()

def try_remove(path):
    print("Deleting", path)
    try:
        os.remove(path)
    except:
        pass

if args.clean:
    print("Cleaning...")
    try_remove(os.path.join(dir_path, "qasan-qemu"))
    try_remove(os.path.join(dir_path, "libqasan.so"))
    try_remove(os.path.join(dir_path, "libqasan", "libqasan.so"))
    # try_remove(output_dso)
    os.system("""cd '%s' ; make clean""" % (os.path.join(dir_path, "qemu")))
    print("Successful clean.")
    print("")
    exit(0)

if args.arch not in ARCHS:
    print("ERROR:", args.arch, "is not a supported architecture.")
    print("Supported architectures are", ", ".join(ARCHS.keys()))
    print("")
    exit(1)

if shutil.which(args.cc) is None and not os.path.isfile(args.cc):
    print("ERROR:", args.cc, " not found.")
    print("Specify another C compiler with --cc")
    print("")
    exit(1)
if shutil.which(args.cxx) is None and not os.path.isfile(args.cxx):
    print("ERROR:", args.cxx, " not found.")
    print("Specify another C++ compiler with --cxx")
    print("")
    exit(1)

# on Ubuntu 18.04: /usr/lib/llvm-8/lib/clang/8.0.0/lib/linux/libclang_rt.asan-x86_64.so
if not os.path.isfile(args.asan_dso):
    print("ERROR:", args.asan_dso, "not found.")
    print("")
    exit(1)

output_dso = os.path.join(dir_path, os.path.basename(args.asan_dso))
lib_dso = os.path.basename(args.asan_dso)
if lib_dso.startswith("lib"): lib_dso = lib_dso[3:]
if lib_dso.endswith(".so"): lib_dso = lib_dso[:-3]

arch = ARCHS[args.arch]

cross_cc = args.cc
if arch in ARCHS_CROSS:
    if args.cross is None:
        cross_cc = "%s-linux-gnu-gcc" % arch
        print("")
        print("WARNING: The selected arch needs a cross compiler for libqasan")
        print("We selected %s by default, use --cross to specify a custom one" % cross_cc)
        print("")
    else:
        cross_cc = args.cross
if shutil.which(cross_cc) is None:
    print("ERROR:", cross_cc, " not found.")
    print("Specify another Cross C compiler with --cross")
    print("")
    exit(1)

def deintercept(asan_dso, output_dso):
    global arch
    print("Patching", asan_dso)
    lib = lief.parse(asan_dso)

    names = []
    for index, symbol in enumerate(lib.symbols):
        if symbol.type == lief.ELF.SYMBOL_TYPES.FUNC and symbol.name.startswith("__interceptor_"):
            names.append(lib.symbols[index].name[len("__interceptor_"):])

    #names = ["malloc", "calloc", "realloc", "valloc", "pvalloc", "memalign", "posix_memalign", "free"]

    for index, symbol in enumerate(lib.symbols):
        if symbol.type == lief.ELF.SYMBOL_TYPES.FUNC and symbol.binding == lief.ELF.SYMBOL_BINDINGS.WEAK and symbol.name in names:
            print("Renaming ", symbol)
            lib.symbols[index].name = "__qasan_" + symbol.name

    lib.write(output_dso)

deintercept(args.asan_dso, output_dso)

cpu_qemu_flag = ""
if arch in ARCHS_32:
    cpu_qemu_flag = "--cpu=i386"
    print("")
    print("WARNING: To do a 32 bit build, you have to install i386 libraries and set PKG_CONFIG_PATH")
    print("If you haven't did it yet, on Ubuntu 18.04 it is PKG_CONFIG_PATH=/usr/lib/i386-linux-gnu/pkgconfig")
    print("")

assert ( os.system("""cd '%s' ; ./configure --target-list="%s-linux-user" --disable-system --enable-pie \
  --cc="%s" --cxx="%s" --extra-cflags="-O3 -ggdb" %s \
  --extra-ldflags="-L %s -l%s -Wl,-rpath,.,-rpath,%s" \
  --enable-linux-user --disable-gtk --disable-sdl --disable-vnc --disable-strip"""
  % (os.path.join(dir_path, "qemu"), arch, args.cc, args.cxx, cpu_qemu_flag,
     dir_path, lib_dso, dir_path)) == 0 )

assert ( os.system("""cd '%s' ; make -j `nproc`""" % (os.path.join(dir_path, "qemu"))) == 0 )

shutil.copy2(
  os.path.join(dir_path, "qemu", arch + "-linux-user", "qemu-" + arch),
  os.path.join(dir_path, "qasan-qemu")
)

libqasan_cflags = ""
if arch == "i386":
    libqasan_cflags = "-m32"

assert ( os.system("""cd '%s' ; make CC='%s' CFLAGS='%s'"""
  % (os.path.join(dir_path, "libqasan"), cross_cc, libqasan_cflags)) == 0 )

shutil.copy2(
  os.path.join(dir_path, "libqasan", "libqasan.so"),
  dir_path
)

print("Successful build.")
print("Test it with ./qasan /bin/ls")
print("")
