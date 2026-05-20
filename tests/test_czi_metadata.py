from pathlib import Path
import struct

from zeiss_browser_qt.czi_attachments import extract_embedded_preview, list_czi_attachments
from zeiss_browser_qt.czi_metadata import extract_czi_xml_metadata


def test_extract_czi_xml_metadata_from_embedded_imagedocument(tmp_path):
    xml = """<ImageDocument>
  <Metadata>
    <Information>
      <Document>
        <CreationDate>2024-01-02T03:04:05Z</CreationDate>
      </Document>
      <Image>
        <SizeX>2048</SizeX>
        <SizeY>1024</SizeY>
        <SizeZ>7</SizeZ>
        <SizeC>2</SizeC>
        <SizeS>3</SizeS>
        <PixelType>Gray16</PixelType>
        <ComponentBitCount>12</ComponentBitCount>
        <Dimensions>
          <S>
            <Scenes>
              <Scene Index="0" Name="P1" />
              <Scene Index="1" Name="P2" />
              <Scene Index="2" Name="P3" />
            </Scenes>
          </S>
        </Dimensions>
        <ImageFrame>0,0,640,480</ImageFrame>
        <AcquisitionDateAndTime>2024-01-02T03:04:05Z</AcquisitionDateAndTime>
      </Image>
    </Information>
    <Scaling>
      <Distance Id="X"><Value>2.5E-07</Value></Distance>
      <Distance Id="Y"><Value>5E-07</Value></Distance>
      <Distance Id="Z"><Value>1E-06</Value></Distance>
    </Scaling>
    <DisplaySetting>
      <Channels>
        <Channel Id="Channel:0" Name="DAPI" />
        <Channel Id="Channel:1" Name="FITC" />
      </Channels>
    </DisplaySetting>
  </Metadata>
</ImageDocument>"""
    czi = tmp_path / "sample.czi"
    czi.write_bytes(b"HEADER" + xml.encode("utf-8") + b"TRAILER")

    metadata = extract_czi_xml_metadata(czi)

    assert metadata["global_size_x"] == 2048
    assert metadata["global_size_y"] == 1024
    assert metadata["xs"] == 640
    assert metadata["ys"] == 480
    assert metadata["zs"] == 7
    assert metadata["channels"] == 2
    assert metadata["tiles"] == 3
    assert metadata["channel_names"] == ["DAPI", "FITC"]
    assert metadata["scene_names"] == ["P1", "P2", "P3"]
    assert metadata["xres2"] == 0.25
    assert metadata["yres2"] == 0.5
    assert metadata["zres2"] == 1.0
    assert metadata["backend_status"] == "xml-metadata"
    assert metadata["placeholder_size_x"] <= 1536
    assert metadata["experiment_datetime"] == "2024-01-02T03:04:05Z"


def test_extract_embedded_preview_from_attachment_directory(tmp_path):
    czi = tmp_path / "preview.czi"
    payload = b"fake-jpeg-payload"
    attachment_dir_position = 512
    attachment_segment_position = 2048

    data = bytearray(4096)
    data[:16] = b"ZISRAWFILE\x00\x00\x00\x00\x00\x00"
    struct.pack_into("<q", data, 104, attachment_dir_position)

    data[attachment_dir_position : attachment_dir_position + 16] = b"ZISRAWATTDIR\x00\x00\x00\x00"
    struct.pack_into("<i", data, attachment_dir_position + 32, 1)

    entry_offset = attachment_dir_position + 288
    data[entry_offset : entry_offset + 2] = b"A1"
    struct.pack_into("<q", data, entry_offset + 12, attachment_segment_position)
    data[entry_offset + 40 : entry_offset + 48] = b"JPG\x00\x00\x00\x00\x00"
    name = b"Thumbnail"
    data[entry_offset + 48 : entry_offset + 48 + len(name)] = name

    data[attachment_segment_position : attachment_segment_position + 16] = b"ZISRAWATTACH\x00\x00\x00\x00"
    struct.pack_into("<q", data, attachment_segment_position + 32, len(payload))
    payload_offset = attachment_segment_position + 288
    data[payload_offset : payload_offset + len(payload)] = payload

    czi.write_bytes(bytes(data))

    attachments = list_czi_attachments(czi)
    assert len(attachments) == 1
    assert attachments[0].name == "Thumbnail"
    assert attachments[0].file_type == "jpg"

    out = extract_embedded_preview(czi, tmp_path)
    assert out is not None
    assert out.suffix == ".jpg"
    assert out.read_bytes() == payload