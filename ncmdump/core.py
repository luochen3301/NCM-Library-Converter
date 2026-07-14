# -*- coding: utf-8 -*-
"""
Created on Sun Jul 15 01:05:58 2018

@author: Nzix

fix by kuon 2025-01-01
"""

import binascii, struct
import base64, json
import os
import tempfile
import time

from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from Crypto.Util.strxor import strxor
from mutagen import mp3, flac, id3
import mutagen

CORE_KEY = binascii.a2b_hex('687A4852416D736F356B496E62617857')
META_KEY = binascii.a2b_hex('2331346C6A6B5F215C5D2630553C2728')
BUFFER_SIZE = 16384
NCM_MAGIC = binascii.a2b_hex('4354454e4644414d')
IDENTIFIER_FLAG = False  #是否提取音频的备注内容

# 细化异常类型体系
class NCMError(Exception):
    """NCM处理基础异常类"""
    pass

class NCMFormatError(NCMError):
    """NCM格式错误"""
    pass

class NCMDecryptError(NCMError):
    """NCM解密过程中的错误"""
    pass

class NCMMetadataError(NCMError):
    """NCM元数据处理错误"""
    pass

class NCMFileIOError(NCMError):
    """NCM文件IO错误"""
    pass

class NCMTaggingError(NCMError):
    """音频文件标签处理错误"""
    pass


class NCMConversionCanceled(NCMError):
    """Raised when a conversion is canceled by the caller.

    Cancellation is deliberately separate from conversion failures so callers
    can leave database state and history untouched.
    """

    pass


def is_valid_audio_output(path, expected_format=None):
    """Return whether *path* is a non-empty MP3/FLAC file of the expected type.

    This intentionally performs a small signature check instead of accepting
    any non-empty file.  A stale or partial file must never be treated as a
    completed conversion merely because it has an audio-looking extension.
    """

    try:
        output = os.fspath(path)
        if not os.path.isfile(output) or os.path.getsize(output) <= 0:
            return False

        extension = os.path.splitext(output)[1].lower().lstrip(".")
        expected = str(expected_format or extension).lower().lstrip(".")
        if expected not in {"mp3", "flac"} or extension != expected:
            return False

        with open(output, "rb") as handle:
            header = handle.read(4096)
        if expected == "flac":
            return header.startswith(b"fLaC")
        if header.startswith(b"ID3"):
            return True
        return len(header) >= 2 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0
    except (OSError, TypeError, ValueError):
        return False

def generate_rc4_keystream(key_data):
    """生成RC4密钥流
    Args:
        key_data: 密钥数据
    Returns:
        bytes: 生成的密钥流
    Raises:
        NCMDecryptError: 密钥流生成失败
    """
    try:
        key_length = len(key_data)
        key = bytearray(key_data)
        S = bytearray(range(256))
        j = 0

        # KSA初始化
        for i in range(256):
            j = (j + S[i] + key[i % key_length]) & 0xFF
            S[i], S[j] = S[j], S[i]

        # 生成密钥流
        stream = [S[(S[i] + S[(i + S[i]) & 0xFF]) & 0xFF] for i in range(256)]
        return bytes(stream[1:] + stream[:1]) * 64
    except Exception as e:
        raise NCMDecryptError(f"RC4密钥流生成失败: {str(e)}")

def read_ncm_file(f):
    """读取NCM文件内容
    Args:
        f: 文件对象
    Returns:
        tuple: (key_stream, meta_data, image_data, identifier)
    Raises:
        NCMFormatError: 无效的NCM文件格式
        NCMDecryptError: 解密过程失败
        NCMMetadataError: 元数据处理失败
    """
    try:
        # 验证文件头
        header = f.read(8)
        if header != NCM_MAGIC:
            raise NCMFormatError("无效的NCM文件头，不是标准NCM文件")

        f.seek(2, 1)

        # 处理密钥数据
        try:
            key_length = struct.unpack('<I', f.read(4))[0]
            key_data = bytes(byte ^ 0x64 for byte in f.read(key_length))
        except struct.error as e:
            raise NCMFormatError(f"读取密钥长度失败: {str(e)}")
        except Exception as e:
            raise NCMDecryptError(f"密钥数据处理失败: {str(e)}")

        try:
            cryptor = AES.new(CORE_KEY, AES.MODE_ECB)
            key_data = unpad(cryptor.decrypt(key_data), 16)[17:]
            key_stream = generate_rc4_keystream(key_data)
        except ValueError as e:
            raise NCMDecryptError(f"AES解密密钥失败: {str(e)}")

        # 处理元数据
        try:
            meta_length = struct.unpack('<I', f.read(4))[0]
            identifier = ""
            if meta_length:
                meta_data = bytes(byte ^ 0x63 for byte in f.read(meta_length))
                identifier = meta_data.decode('utf-8') if IDENTIFIER_FLAG else ""
                meta_data = base64.b64decode(meta_data[22:])
                
                cryptor = AES.new(META_KEY, AES.MODE_ECB)
                meta_data = unpad(cryptor.decrypt(meta_data), 16).decode('utf-8')
                meta_data = json.loads(meta_data[6:])
            else:
                meta_data = {'format': 'flac' if os.fstat(f.fileno()).st_size > 1024 ** 2 * 16 else 'mp3'}
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise NCMMetadataError(f"元数据解析失败: {str(e)}")
        except Exception as e:
            raise NCMDecryptError(f"元数据处理失败: {str(e)}")

        # 处理图片数据
        try:
            f.seek(5, 1)
            image_space = struct.unpack('<I', f.read(4))[0]
            image_size = struct.unpack('<I', f.read(4))[0]
            image_data = f.read(image_size) if image_size else None
            f.seek(image_space - image_size, 1)
        except struct.error as e:
            raise NCMFormatError(f"读取图片数据结构失败: {str(e)}")
        except Exception as e:
            raise NCMDecryptError(f"图片数据处理失败: {str(e)}")

        return key_stream, meta_data, image_data, identifier
    except (NCMFormatError, NCMDecryptError, NCMMetadataError) as e:
        # 直接传递已定义的异常
        raise
    except IOError as e:
        raise NCMFileIOError(f"文件读取错误: {str(e)}")
    except Exception as e:
        raise NCMDecryptError(f"读取NCM文件时发生未知错误: {str(e)}")

def _raise_if_canceled(cancel_callback):
    if cancel_callback and cancel_callback():
        raise NCMConversionCanceled("Conversion canceled")


def _wait_until_resumed(pause_callback, cancel_callback):
    while pause_callback and pause_callback():
        _raise_if_canceled(cancel_callback)
        time.sleep(0.1)
    _raise_if_canceled(cancel_callback)


def _write_media_tags(path, meta_data, image_data, identifier):
    media_format = str(meta_data.get("format") or "").lower().lstrip(".")

    def embed(item, content, picture_type):
        item.encoding = 0
        item.type = picture_type
        item.mime = "image/png" if content[:4] == binascii.a2b_hex("89504E47") else "image/jpeg"
        item.data = content

    try:
        if image_data:
            if media_format == "flac":
                picture_audio = flac.FLAC(path)
                image = flac.Picture()
                embed(image, image_data, 3)
                picture_audio.clear_pictures()
                picture_audio.add_picture(image)
            else:
                picture_audio = mp3.MP3(path)
                if picture_audio.tags is None:
                    picture_audio.add_tags()
                image = id3.APIC()
                embed(image, image_data, 6)
                picture_audio.tags.add(image)
            picture_audio.save()

        if media_format == "flac":
            audio = flac.FLAC(path)
            audio["description"] = identifier
        else:
            audio = mp3.EasyMP3(path)
            if audio.tags is None:
                audio.add_tags()
            audio.tags.RegisterTextKey("comment", "COMM")
            audio["comment"] = identifier

        audio["title"] = meta_data.get("musicName", "Unknown track")
        audio["album"] = meta_data.get("album", "Unknown album")
        artist_list = meta_data.get("artist", [])
        artists = [
            artist[0]
            for artist in artist_list
            if isinstance(artist, (list, tuple)) and artist and artist[0]
        ] if isinstance(artist_list, list) else []
        audio["artist"] = "/".join(artists) if artists else "Unknown artist"
        audio.save()
    except NCMError:
        raise
    except (mutagen.MutagenError, KeyError, TypeError, ValueError) as exc:
        raise NCMTaggingError(f"Could not write audio metadata: {exc}") from exc


def dump(
    input_path,
    output_path=None,
    skip=True,
    progress_callback=None,
    pause_callback=None,
    cancel_callback=None,
):
    """Decrypt one NCM file and atomically publish the resulting audio file.

    The public return value remains the final output path. Audio bytes and
    metadata are written to a same-directory temporary file whose suffix still
    identifies the real media format. The destination is replaced only after
    metadata writing succeeds, so cancellation and failure never leave a
    partial final file behind.
    """

    input_path = os.fspath(input_path)
    output_path_generator = output_path
    if output_path_generator is None:
        output_path_generator = lambda path, meta: os.path.splitext(path)[0] + "." + meta["format"]
    elif not callable(output_path_generator):
        requested_path = os.fspath(output_path_generator)
        output_path_generator = lambda _path, _meta: requested_path

    temporary_path = ""
    try:
        _raise_if_canceled(cancel_callback)
        with open(input_path, "rb") as source:
            key_stream, meta_data, image_data, identifier = read_ncm_file(source)
            media_format = str(meta_data.get("format") or "").lower().lstrip(".")
            if media_format not in {"mp3", "flac"}:
                raise NCMMetadataError(f"Unsupported audio format: {media_format or 'unknown'}")

            final_path = os.path.abspath(os.fspath(output_path_generator(input_path, meta_data)))
            if os.path.splitext(final_path)[1].lower() != f".{media_format}":
                raise NCMMetadataError(
                    f"Output suffix must match the decrypted {media_format.upper()} audio format."
                )

            _raise_if_canceled(cancel_callback)
            if skip and is_valid_audio_output(final_path, media_format):
                size = os.path.getsize(final_path)
                if progress_callback:
                    progress_callback(size, size, final_path)
                return final_path

            output_directory = os.path.dirname(final_path)
            os.makedirs(output_directory, exist_ok=True)
            descriptor, temporary_path = tempfile.mkstemp(
                prefix=f".{os.path.splitext(os.path.basename(final_path))[0]}.ncmdump-",
                suffix=f".{media_format}",
                dir=output_directory,
            )
            os.close(descriptor)

            total_bytes = max(0, os.fstat(source.fileno()).st_size - source.tell())
            written_bytes = 0
            try:
                with open(temporary_path, "wb") as output:
                    while True:
                        _wait_until_resumed(pause_callback, cancel_callback)
                        data = source.read(BUFFER_SIZE)
                        if not data:
                            break
                        output.write(strxor(data, key_stream[:len(data)]))
                        written_bytes += len(data)
                        if progress_callback:
                            progress_callback(written_bytes, total_bytes, final_path)
                    output.flush()
                    os.fsync(output.fileno())
            except NCMConversionCanceled:
                raise
            except OSError as exc:
                raise NCMFileIOError(f"Could not write decrypted audio: {exc}") from exc

            _raise_if_canceled(cancel_callback)
            _write_media_tags(temporary_path, meta_data, image_data, identifier)
            _raise_if_canceled(cancel_callback)

            try:
                os.replace(temporary_path, final_path)
                temporary_path = ""
            except OSError as exc:
                raise NCMFileIOError(f"Could not publish converted audio: {exc}") from exc
            return final_path
    except NCMConversionCanceled:
        raise
    except (NCMFormatError, NCMDecryptError, NCMMetadataError, NCMFileIOError, NCMTaggingError):
        raise
    except OSError as exc:
        raise NCMFileIOError(f"Could not open or process '{input_path}': {exc}") from exc
    except Exception as exc:
        raise NCMError(f"Unexpected NCM conversion error: {exc}") from exc
    finally:
        if temporary_path:
            try:
                os.remove(temporary_path)
            except FileNotFoundError:
                pass
            except OSError:
                # The final destination remains safe even if an external lock
                # prevents immediate cleanup of the private temporary file.
                pass


def _legacy_dump(
    input_path,
    output_path=None,
    skip=True,
    progress_callback=None,
    pause_callback=None,
    cancel_callback=None,
):
    """
    NCM文件解密主函数
    Args:
        input_path: NCM文件路径
        output_path: 输出文件路径
        skip: 是否跳过已存在的文件
        progress_callback: 可选进度回调，签名为 (written_bytes, total_bytes, output_path)
        pause_callback: 可选暂停回调，返回 True 时暂停写入
        cancel_callback: 可选取消回调，返回 True 时中止转换
    Returns:
        str: 输出文件路径
    Raises:
        NCMFileIOError: 文件读写错误
        NCMFormatError: 无效的NCM文件格式
        NCMDecryptError: 解密过程失败
        NCMMetadataError: 元数据处理失败
        NCMTaggingError: 标签处理失败
        NCMError: 其他NCM处理错误
    """
    output_path = (lambda path, meta: os.path.splitext(path)[0] + '.' + meta['format']) if not output_path else output_path
    output_path_generator = (lambda path, meta: output_path) if not callable(output_path) else output_path

    try:
        with open(input_path, 'rb') as f:
            try:
                key_stream, meta_data, image_data, identifier = read_ncm_file(f)

                # media data
                output_path = output_path_generator(input_path, meta_data)
                if skip and os.path.exists(output_path):
                    if progress_callback:
                        progress_callback(os.path.getsize(output_path), os.path.getsize(output_path), output_path)
                    return output_path

                # 写入解密后的音频数据
                try:
                    total_bytes = max(0, os.fstat(f.fileno()).st_size - f.tell())
                    written_bytes = 0
                    with open(output_path, 'wb') as m:
                        while True:
                            while pause_callback and pause_callback():
                                if cancel_callback and cancel_callback():
                                    raise NCMError("转换已取消")
                                time.sleep(0.1)
                            if cancel_callback and cancel_callback():
                                raise NCMError("转换已取消")
                            data = f.read(BUFFER_SIZE)  # 使用定义的常量
                            if not data:
                                break
                            data = strxor(data, key_stream[:len(data)])  # 使用密钥流解密
                            m.write(data)
                            written_bytes += len(data)
                            if progress_callback:
                                progress_callback(written_bytes, total_bytes, output_path)
                except IOError as e:
                    raise NCMFileIOError(f"写入解密数据失败: {str(e)}")

                # media tag
                def embed(item, content, type):
                    """嵌入封面图片的辅助函数"""
                    item.encoding = 0
                    item.type = type
                    item.mime = 'image/png' if content[0:4] == binascii.a2b_hex('89504E47') else 'image/jpeg'
                    item.data = content

                try:
                    # 处理封面图片
                    if image_data:
                        if meta_data['format'] == 'flac':
                            audio = flac.FLAC(output_path)
                            image = flac.Picture()
                            embed(image, image_data, 3)
                            audio.clear_pictures()
                            audio.add_picture(image)
                        elif meta_data['format'] == 'mp3':
                            audio = mp3.MP3(output_path)
                            image = id3.APIC()
                            embed(image, image_data, 6)
                            audio.tags.add(image)
                        audio.save()

                    # 处理音频标签
                    if meta_data['format'] == 'flac':
                        audio = flac.FLAC(output_path)
                        audio['description'] = identifier
                    else:
                        audio = mp3.EasyMP3(output_path)
                        audio['title'] = 'placeholder'
                        audio.tags.RegisterTextKey('comment', 'COMM')
                        audio['comment'] = identifier
                    
                    # 设置公共标签
                    audio['title'] = meta_data.get('musicName', '未知曲目')
                    audio['album'] = meta_data.get('album', '未知专辑')
                    # 安全获取艺术家列表
                    artist_list = meta_data.get('artist', [])
                    if artist_list and isinstance(artist_list, list) and len(artist_list) > 0:
                        audio['artist'] = '/'.join([artist[0] for artist in artist_list if isinstance(artist, list) and len(artist) > 0])
                    else:
                        audio['artist'] = '未知艺术家'
                    audio.save()
                except (mutagen.MutagenError, KeyError) as e:
                    raise NCMTaggingError(f"音频标签处理失败: {str(e)}")

                return output_path
            
            except (NCMFormatError, NCMDecryptError, NCMMetadataError, NCMFileIOError, NCMTaggingError) as e:
                # 直接传递定义的异常
                raise
            except Exception as e:
                raise NCMError(f"处理NCM文件时发生未知错误: {str(e)}")
    except IOError as e:
        raise NCMFileIOError(f"无法打开文件 '{input_path}': {str(e)}")
    except Exception as e:
        if isinstance(e, NCMError):
            # 如果已经是NCM类型的错误，直接传递
            raise
        # 捕获其他所有异常并转换为通用NCM错误
        raise NCMError(f"发生未知错误: {str(e)}")
