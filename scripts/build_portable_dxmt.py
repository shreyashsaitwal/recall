#!/usr/bin/env python3
"""Reconstruct and build the accepted DXMT patch against freshly built Wine tools."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil

import sign_pe

ROOT=Path(__file__).resolve().parents[1]
BASE='53ac94701fa76e6696af0926e18f913c5a2e5ffa'
HEADERS='9df86f2341616ef1888ae59919feaa6d4fad693d'
# NVIDIA's NVAPI headers (MIT), a submodule of the base, for DXMT's NVAPI stand-in.
NVAPI='d08488fcc82eef313b0464db37d2955709691e94'
# MetalFX upscaling (1.3): DXMT's DLSS stand-in is signed with Recall's own certificate.
SIGNING=ROOT/'runtime/signing/recall-nvngx'


def run(*args,**kwargs):return subprocess.run([str(a) for a in args],check=True,**kwargs)


def prepare_source(work):
    """DXMT at its pinned commit with the accepted patches, in WORK/dxmt-source. It is all the app
    build needs (build_native_app.py --workspace WORK): its pipeline sources come from here."""
    source=work/'dxmt-source'
    if not source.exists():run('git','clone','--no-checkout','https://github.com/shreyashsaitwal/dxmt',source)
    current=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
    if current!=BASE:run('git','-C',source,'checkout','--detach',BASE)
    run('git','-C',source,'submodule','update','--init','--recursive')
    current=subprocess.check_output(['git','-C',str(source/'include/native/directx'),'rev-parse','HEAD'],text=True).strip()
    if current!=HEADERS:raise ValueError('DirectX header identity mismatch')
    current=subprocess.check_output(['git','-C',str(source/'external/nvapi'),'rev-parse','HEAD'],text=True).strip()
    if current!=NVAPI:raise ValueError('NVAPI header identity mismatch')
    patch=ROOT/'patches/dxmt-v1-private.patch'
    if hashlib.sha256(patch.read_bytes()).hexdigest()!='0d800ecb518731b1041e54b48e022c05771c075726d69101a403d80eec4ced79':raise ValueError('Accepted renderer patch changed')
    check=subprocess.run(['git','apply','--check',str(patch)],cwd=source,capture_output=True)
    if check.returncode==0:run('git','apply',patch,cwd=source)
    else:run('git','apply','--reverse','--check',patch,cwd=source)
    # v1.0: the play-tested performance work (DXMT replay branch e873a90) on top.
    performance=ROOT/'patches/dxmt-v1-performance.patch'
    if hashlib.sha256(performance.read_bytes()).hexdigest()!='102b9665738674907e7aeeb39e9eb659f7cec1e8e5f916a54d93e1934bd0746e':raise ValueError('Accepted performance patch changed')
    check=subprocess.run(['git','apply','--check',str(performance)],cwd=source,capture_output=True)
    if check.returncode==0:run('git','apply',performance,cwd=source)
    else:run('git','apply','--reverse','--check',performance,cwd=source)
    portable_patch=ROOT/'patches/dxmt-portable-metal.patch'
    check=subprocess.run(['git','apply','--check',str(portable_patch)],cwd=source,capture_output=True)
    if check.returncode==0:run('git','apply',portable_patch,cwd=source)
    else:run('git','apply','--reverse','--check',portable_patch,cwd=source)
    # 1.3: DLSS on MetalFX. Direct3D 12 entry points and NVIDIA's failure codes in the DLSS
    # stand-in, and a d3d12.dll whose device only answers NVIDIA Streamline's setup questions.
    # MetalFX writes the DLSS output with shader-write usage (the 1.2 compression keeps it from
    # render targets the game never writes as UAVs); jittered motion vectors lose the jitter change
    # (a pass macOS compiles at run time); the chosen mode is the floor of the dynamic range; and the
    # stand-in logs what the game passes. Sharpening after MetalFX (d3d11.metalfxSharpness, Recall's
    # Sharpening setting) is a contrast-adaptive pass, also compiled at run time.
    metalfx=ROOT/'patches/dxmt-metalfx-upscaling.patch'
    if hashlib.sha256(metalfx.read_bytes()).hexdigest()!='8075dc2b4af2d249e5a354e7584f233c02b89b85d58c8e0d9b2e58fccb6e47dd':raise ValueError('Accepted MetalFX patch changed')
    check=subprocess.run(['git','apply','--check',str(metalfx)],cwd=source,capture_output=True)
    if check.returncode==0:run('git','apply',metalfx,cwd=source)
    else:run('git','apply','--reverse','--check',metalfx,cwd=source)
    # 1.4: the shader pack holds every learned pipeline. Its archives are hashed in pieces instead
    # of read whole, have no total size limit, and can be prepared in batches that each add one
    # (DXMT_PIPELINE_CACHE_APPEND); learning goes on until the disk is nearly full.
    shader_pack=ROOT/'patches/dxmt-shader-pack.patch'
    if hashlib.sha256(shader_pack.read_bytes()).hexdigest()!='22d0335c7b91ae586ed16a085a18f08d27b33cbf4b0bc090fe5552ae92f1d6d5':raise ValueError('Accepted shader pack patch changed')
    check=subprocess.run(['git','apply','--check',str(shader_pack)],cwd=source,capture_output=True)
    if check.returncode==0:run('git','apply',shader_pack,cwd=source)
    else:run('git','apply','--reverse','--check',shader_pack,cwd=source)
    # 1.6.3 (REC-76): GPU errors. Each GPU error is sorted (hang, fault, a bystander discarded), logged
    # with the encoder that was running (DXMT_GPU_ERROR_DETAIL) and recorded beside the session's logs
    # (DXMT_GPU_REPORT); MetalFX starts its history again after one and, after a hang, can move from
    # the Neural Engine to the GPU (DXMT_METALFX_GPU_AFTER_HANG); once macOS has revoked the game's GPU
    # access nothing can be drawn again, so the game ends (DXMT_GPU_LOST_EXIT).
    gpu_errors=ROOT/'patches/dxmt-gpu-errors.patch'
    if hashlib.sha256(gpu_errors.read_bytes()).hexdigest()!='c9ce885185d1a17b16c5ae70a8ba4878a49185452be09d5f8c1400dd82a881bc':raise ValueError('Accepted GPU errors patch changed')
    check=subprocess.run(['git','apply','--check',str(gpu_errors)],cwd=source,capture_output=True)
    if check.returncode==0:run('git','apply',gpu_errors,cwd=source)
    else:run('git','apply','--reverse','--check',gpu_errors,cwd=source)
    # Stream output through a point pass-through geometry shader, which Overwatch uses for the buffer
    # behind many particle effects: every such draw was dropped and the effects flickered.
    stream_output=ROOT/'patches/dxmt-stream-output.patch'
    if hashlib.sha256(stream_output.read_bytes()).hexdigest()!='ce99733a5e70c25972b1142f74babc379951aaccdb8c01521e385b26af2b12b6':raise ValueError('Accepted stream output patch changed')
    check=subprocess.run(['git','apply','--check',str(stream_output)],cwd=source,capture_output=True)
    if check.returncode==0:run('git','apply',stream_output,cwd=source)
    else:run('git','apply','--reverse','--check',stream_output,cwd=source)
    return source,{'patch':patch,'performance':performance,'portable':portable_patch,'metalfx':metalfx,'shader_pack':shader_pack,
                   'gpu_errors':gpu_errors,'stream_output':stream_output}


def build(work,tools,jobs,signing=SIGNING):
    if not (signing/sign_pe.KEY).is_file():raise ValueError(f'No signing certificate in {signing} (scripts/sign_pe.py create-certificate)')
    source,patches=prepare_source(work);builddir=work/'dxmt-build';install=work/'dxmt-install'
    patch,performance,portable_patch,metalfx,shader_pack,gpu_errors,stream_output=(patches[k] for k in ('patch','performance','portable','metalfx','shader_pack','gpu_errors','stream_output'))
    wrapper=source/'portable_metal.py'
    shutil.copy2(ROOT/'scripts/portable_metal.py',wrapper);wrapper.chmod(0o755)
    env=os.environ.copy();env.pop('DESTDIR',None)
    env['PATH']=':'.join([str(tools/'llvm-mingw-20251216-ucrt-macos-universal/bin'),str(tools/'python/bin'),'/usr/bin','/bin','/usr/sbin','/sbin'])
    meson=tools/'python/bin/meson'
    setup=[meson,'setup',builddir,source,'--cross-file',source/'build-win64.txt','--buildtype=release',
           '--prefix',install,'--strip','-Dnative_llvm_path='+str(tools/'clang+llvm-15.0.7-x86_64-apple-darwin21.0'),
           '-Dwine_build_path='+str(work/'wine-build'),'-Denable_tests=false','-Denable_nvapi=true',
           '-Denable_nvngx=true','-Denable_d3d12=false']
    if (builddir/'meson-private/coredata.dat').exists():setup.append('--reconfigure')
    run(*setup,env=env)
    run(meson,'compile','-C',builddir,'-j',jobs,env=env)
    run(meson,'install','-C',builddir,'--no-rebuild',env=env)
    # NVIDIA's NGX loader loads only a signed core DLL; signing follows winebuild --builtin.
    nvngx=install/'x86_64-windows/nvngx.dll'
    sign_pe.sign(signing,nvngx,nvngx)
    if not sign_pe.check(nvngx,signing):raise ValueError('nvngx.dll signature check failed')
    files={str(p.relative_to(install)):hashlib.sha256(p.read_bytes()).hexdigest()
           for p in install.rglob('*') if p.is_file()}
    (work/'dxmt-build-proof.json').write_text(json.dumps({'base':BASE,'headers':HEADERS,
        'patch_sha256':hashlib.sha256(patch.read_bytes()).hexdigest(),'files':files,
        'performance_patch_sha256':hashlib.sha256(performance.read_bytes()).hexdigest(),
        'metalfx_patch_sha256':hashlib.sha256(metalfx.read_bytes()).hexdigest(),'nvapi':NVAPI,
        'shader_pack_patch_sha256':hashlib.sha256(shader_pack.read_bytes()).hexdigest(),
        'gpu_errors_patch_sha256':hashlib.sha256(gpu_errors.read_bytes()).hexdigest(),
        'stream_output_patch_sha256':hashlib.sha256(stream_output.read_bytes()).hexdigest(),
        'nvngx_certificate_sha256':hashlib.sha256((signing/sign_pe.LEAF).read_bytes()).hexdigest(),
        'portable_metal_patch_sha256':hashlib.sha256(portable_patch.read_bytes()).hexdigest(),
        'portable_metal_wrapper_sha256':hashlib.sha256(wrapper.read_bytes()).hexdigest(),
        'developer_dir':env.get('DEVELOPER_DIR','xcode-select'),'sdkroot':env.get('SDKROOT','default'),
        'metal_cache':'used' if env.get('DXMT_METAL_CACHE') else 'none',
        'wine_build_tools':'fresh Phase 2 source build'},indent=2)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--workspace',type=Path,required=True)
    p.add_argument('--toolchains',type=Path,default=ROOT/'runtime/toolchains');p.add_argument('--jobs',type=int,choices=range(1,5),default=2)
    p.add_argument('--source-only',action='store_true',help='only fetch and patch DXMT (enough for build_native_app.py --workspace); no toolchains or signing needed')
    a=p.parse_args()
    if a.source_only:a.workspace.mkdir(parents=True,exist_ok=True);prepare_source(a.workspace.resolve())
    else:build(a.workspace.resolve(),a.toolchains.resolve(),a.jobs)
