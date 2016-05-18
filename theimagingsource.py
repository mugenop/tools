import ctypes as C
import numpy as np
try:
    import np_tif
except ImportError: # You won't be able to save as TIF
    np_tif = None

class DMK_x3GP031:
    def __init__(self, verbose=True):
        # Find the camera
        num_devices = dll.get_device_count()
        for d in range(num_devices):
            name = dll.get_unique_name_from_list(d)
            if len(name.split()) == 3:
                if name.split()[0] == b'DMK': # Might be our camera...
                    if name.split()[1] in (b'33GP031', b'23GP031'): # It is!
                        if verbose:
                            print('Camera found, named:', name.decode('ascii'))
                        break
        else:
            raise UserWarning("Failed to find a DMK *3GP031 camera.\n" +
                              "Is the camera plugged in?")
        self.name = name
        self.live = False
        # Take custody of the camera
        self.handle = dll.create_grabber()
        assert dll.open_by_name(self.handle, self.name) == dll.success
        assert dll.is_valid(self.handle) == dll.success
        # Figure out what video formats (ROI and bit depth) are
        # supported, and set the format to our preferred default
        num_formats = dll.get_video_format_count(self.handle)
        self.video_formats = []
        for f in range(num_formats):
            fmt = dll.get_video_format(self.handle, f)
            self.video_formats.append(fmt)
        assert b'Y16 (2592x1944)' in self.video_formats
        self.set_video_format(verbose=verbose)
        self.set_exposure(exposure_seconds=0.1, verbose=verbose)
        self.enable_trigger(False)
        
        return None

    def set_video_format(self, video_format=b'Y16 (2592x1944)', verbose=True):
        try: # 'video_format' is either represented as bytes...
            video_format = bytes(video_format)
        except TypeError: # ...or as an ascii string:
            video_format = bytes(video_format, encoding='ascii')
        assert video_format.startswith(b"Y16") # Only 16-bit mode is supported
        if video_format not in self.video_formats: # Try to crash helpfully
            print("***Error: format not available***\n", "Available formats:")
            for fmt in self.video_formats:
                if fmt.startswith(b'Y16'): print(fmt)
            raise UserWarning("Requested video format [" +
                              str(video_format) +
                              "] not available")
        if verbose: print(" Setting video format to:", video_format.decode())
        assert dll.set_video_format(self.handle, video_format) == dll.success
        # The camera supports both 8-bit mode and 16-bit mode (12 bits
        # stored in a 16-bit format). I've chosen to only allow 16-bit
        # mode. However, the documentation for the 16-bit mode is a
        # bit... incomplete, in my opinion. I *believe* the following
        # mysterious incantation ensures we're in 16-bit mode.
        #
        # First, you have to remove the overlay. I don't know what that
        # is, but it's required for Y16 operation. This is not yet well
        # documented, but if you read tisgrabber.h, you see this
        # mentioned.
        assert dll.remove_overlay(self.handle, 0) == dll.success
        # Now, we set the "sink format" to Y16. You can only set the
        # sink format when the camera is not live, I think.
        if self.live: self.stop_live(verbose)
        Y16_mode = 4
        assert dll.set_format(self.handle, Y16_mode) == dll.success
        # Now we want to check if we succeeded in setting the "sink
        # format". However, you cannot call get_format until the camera
        # has started live at least once!
        self.start_live(verbose=False)
        self.stop_live(verbose=False)
        assert dll.get_format(self.handle) == Y16_mode
        # Finally, we should check that our changes to the video and
        # sink format were successful, and update the corresponding
        # attributes:
        self.get_image_information(verbose=verbose)
        return None

    def get_image_information(self, verbose=True):
        # I believe this function doesn't work until the video format
        # and sink format are set. This *should* be taken care of by
        # set_video_format...
        width, height = C.c_long(100), C.c_long(101)
        bit_depth, color = C.c_int(102), C.c_int(103)
        assert dll.get_image_description(
            self.handle, width, height, bit_depth, color) == dll.success
        assert bit_depth.value == 16
        assert color.value == 4 # Y16
        self.width, self.height = width.value, height.value
        self.bit_depth = bit_depth.value
        if verbose:
            print(" Camera image format: ", self.width, "x", self.height,
                  " ", self.bit_depth, "-bit", sep='')
        return None

    def set_exposure(self, exposure_seconds, verbose=True):
        # First we ensure autoexposure is disabled (required to set exposure...)
        autoexposure = C.c_int(777)
        assert dll.get_auto_property(self.handle, dll.exposure, autoexposure
                                     ) == dll.success
        assert autoexposure.value in (0, 1)
        if autoexposure.value == 1:
            if verbose: print(" Deactivating autoexposure... ", end='')
            assert dll.set_auto_property(self.handle, dll.exposure, 0
                                         ) == dll.success
            assert dll.get_auto_property(self.handle, dll.exposure, autoexposure
                                         ) == dll.success
            assert autoexposure.value == 0
            if verbose: print("done.")
        # Next find min and max allowed values for exposure    
        min_exp, max_exp = C.c_long(777), C.c_long(778)
        assert dll.get_property_range(
            self.handle, dll.exposure, min_exp, max_exp) == dll.success
        # Check that the requested exposure value is allowed
        exposure_microseconds = int(exposure_seconds * 1e6)
        if not min_exp.value < exposure_microseconds < max_exp.value:
            print("Minimum exposure:", min_exp.value * 1e-6, "(s)")
            print("Maximum exposure:", max_exp.value * 1e-6, "(s)")
            raise UserWarning("Requested exposure is not possible")
        # Now set the exposure
        assert dll.set_property(
            self.handle, dll.exposure, exposure_microseconds) == dll.success
        self.get_exposure(verbose=verbose)
        return None

    def get_exposure(self, verbose=True):
        exposure = C.c_long(777)
        assert dll.get_property(
            self.handle, dll.exposure, exposure) == dll.success
        self.exposure_microseconds = exposure.value
        self.exposure_seconds = self.exposure_microseconds * 1e-6
        self.exposure_milliseconds = self.exposure_microseconds * 1e-3
        if verbose:
            print(" Camera exposure: %0.6f seconds"%self.exposure_seconds)
        return None

    def start_live(self, verbose=True):
        if verbose: print(" Starting live...", end='')
        assert dll.success == dll.start_live(self.handle, 0)
        self.live = True
        if verbose: print(" done")
        return None

    def stop_live(self, verbose=True):
        if verbose: print(" Stopping live...", end='')
        assert dll.stop_live(self.handle) == None
        self.live = False
        if verbose: print(" done")
        return None

    def snap(
        self,
        filename=None,
        timeout_milliseconds=None,
        verbose=True,
        output_array=None):
        if filename is None and output_array is None:
            print("When the camera snaps an image, where is the data going?")
            print("Disk? (set 'filename')")
            print("Memory? (set 'output_array')")
            print("You didn't set either one. No good.")
            raise UserWarning("Where should the camera put the snapped image?")
        if verbose: print(" Snapping:")
        # I believe this is true: If you want the fastest frame rate,
        # you should leave the camera in "live" mode and snap, snap,
        # snap. However, a camera in "live" mode will occasionally
        # mistake noise on the trigger line for a real trigger. If you
        # want to minimize the rate of false triggers, you should turn
        # "live" mode on and off as quickly as possible before and after
        # each snap.
        #
        # This code block tries to accept both behaviors:
        # 1.  If we're in live mode, just snap.
        # 2.  If we're not in live mode, go live, snap, stop live.
        if self.live:
            already_live = True
        else:
            self.start_live(verbose=verbose)
            already_live = False
        if timeout_milliseconds is None: # No timeout; wait forever
            timeout_milliseconds = -1
        timeout_milliseconds = int(timeout_milliseconds)
        assert dll.snap_image(self.handle, timeout_milliseconds) == dll.success
        # If we temporarily went live, set live back to "stop":
        if not already_live:
            self.stop_live(verbose=verbose)
        if filename is not None:
            self._save_snapped_image_as_tif(filename, verbose)
        if output_array is not None:
            self._copy_snapped_image_to_numpy_array(output_array, verbose)
        return None

    def _save_snapped_image_as_tif(self, filename, verbose=True):
        # Don't call this method directly; it should be a side effect of
        # calling the 'snap' method.
        if np_tif is None: 
            raise UserWarning(
                "If you want to save as TIF, get np_tif.py here:\n  " +
                "https://github.com/AndrewGYork/tools/blob/master/np_tif.py\n" +
                "We failed to import np_tif.py.\n" +
                "This means we can't save camera images as TIFs.")
        assert filename.endswith('.tif')
        if verbose:
            print(" Saving a", image.shape, image.dtype, "image as",
                  filename, "...", end='')
        np_tif.array_to_tif(self._snapped_image_as_numpy_array(), filename)
        if verbose: print("done")
        return None

    def _copy_snapped_image_to_numpy_array(
        self, output_array=None, verbose=True):
        # Don't call this method directly; it should be a side effect of
        # calling the 'snap' method.
        image = _snapped_image_as_numpy_array()
        if output_array is None: # We have to allocate memory to hold the output
            return image.copy()
        else: # The user provided an array to copy the snapped image into
            assert output_array.shape == image.shape
            assert output_array.dtype == image.dtype
            output_array[:] = image
            return None

    def _snapped_image_as_numpy_array(self):
        # Don't call this method directly; it should be a side effect of
        # calling the 'snap' method.
        pointer = dll.get_image_pointer(self.handle)
        bytes_per_pixel = self.bit_depth // 8
        bytes_per_image = self.width * self.height * bytes_per_pixel
        image = np.ctypeslib.as_array(pointer, (bytes_per_image,))
        image = image.view(dtype=np.uint16) #The only supported bit depth
        image = image.reshape(self.height, self.width)
        image = np.right_shift(image, 4) # Because 12 bits is stored as 16 bits?
        return image

    def enable_trigger(self, enable=True):
        # True to enable external triggering, False to disable.
        assert dll.is_trigger_available(self.handle) == 1
        # EnableTrigger does NOT return dll.success when it succeeds,
        # even though the documentation says it should:
        print(dll.enable_trigger(self.handle, enable))
        return None

    def send_trigger(self):
        # Send a software trigger to fire the device when in triggered mode.
        assert dll.software_trigger(self.handle) == dll.success
        return None

    def close(self, verbose=True):
        if self.live:
            self.stop_live(verbose)
        dll.release_grabber(self.handle)
        if verbose: print("Camera closed.")
        return None

def main():
    camera = DMK_x3GP031()
    camera.set_video_format("Y16 (1024x768)")
    camera.set_exposure(0.1)
    camera.snap(filename='test.tif')
    camera.close()

# DLL management
try: # Load the DLL
    dll = C.windll.LoadLibrary('tisgrabber_x64')
except (OSError,): # If you fail to load, try to give useful clues.
    print("Failed to load tisgrabber_x64.dll")
    print("\n***\nYou need this to run cameras from TheImagingSource\n***\n")
    print("You also need TIS_DShowLib10_x64.dll and TIS_UDSHL10_x64.dll")
    print("You get these three DLLs from TheImagingSource's website.")
    raise

class GrabberHandle_t(C.Structure):
    _fields_ = [('unused', C.c_int)]

GrabberHandle = C.POINTER(GrabberHandle_t)

dll.success = 1
dll.error = 0
dll.exposure = 4

dll.init = dll.IC_InitLibrary
dll.init.argtypes = [C.c_char_p]
dll.init.restype = C.c_int

dll.get_device_count = dll.IC_GetDeviceCount
dll.get_device_count.argtypes = []
dll.get_device_count.restype = C.c_int

dll.get_unique_name_from_list = dll.IC_GetUniqueNamefromList
dll.get_unique_name_from_list.argtypes = [C.c_int]
dll.get_unique_name_from_list.restype = C.c_char_p

dll.create_grabber = dll.IC_CreateGrabber
dll.create_grabber.argtypes = []
dll.create_grabber.restype = GrabberHandle

dll.open_by_name = dll.IC_OpenDevByUniqueName
dll.open_by_name.argtypes = [GrabberHandle, C.c_char_p]
dll.open_by_name.restype = C.c_int

dll.is_valid = dll.IC_IsDevValid
dll.is_valid.argtypes = [GrabberHandle]
dll.is_valid.restype = C.c_int

dll.get_video_format_count = dll.IC_GetVideoFormatCount
dll.get_video_format_count.argtypes = [GrabberHandle]
dll.get_video_format_count.restype = C.c_int

dll.get_video_format = dll.IC_GetVideoFormat
dll.get_video_format.argtypes = [GrabberHandle, C.c_int]
dll.get_video_format.restype = C.c_char_p

dll.set_video_format = dll.IC_SetVideoFormat
dll.set_video_format.argtypes = [GrabberHandle, C.c_char_p]
dll.set_video_format.restype = C.c_int

dll.get_image_description = dll.IC_GetImageDescription
dll.get_image_description.argtypes = [GrabberHandle,
                                      C.POINTER(C.c_long),
                                      C.POINTER(C.c_long),
                                      C.POINTER(C.c_int),
                                      C.POINTER(C.c_int)]
dll.get_image_description.restype = C.c_int

dll.remove_overlay = dll.IC_RemoveOverlay
dll.remove_overlay.argtypes = [GrabberHandle, C.c_int]

dll.get_format = dll.IC_GetFormat
dll.get_format.argtypes = [GrabberHandle]
dll.get_format.restype = C.c_int

dll.set_format = dll.IC_SetFormat
dll.set_format.argtypes = [GrabberHandle, C.c_int]
dll.set_format.restype = C.c_int

dll.start_live = dll.IC_StartLive
dll.start_live.argtypes = [GrabberHandle, C.c_int] # pass 1 for video, 0 ignore
dll.start_live.restype = C.c_int

dll.snap_image = dll.IC_SnapImage
dll.snap_image.argtypes = [GrabberHandle, C.c_int] # pass timeout in ms
dll.snap_image.restype = C.c_int

dll.get_image_pointer = dll.IC_GetImagePtr
dll.get_image_pointer.argtypes = [GrabberHandle]
dll.get_image_pointer.restype = C.POINTER(C.c_ubyte)

dll.stop_live = dll.IC_StopLive
dll.stop_live.argtypes = [GrabberHandle]
dll.stop_live.restype = None

dll.release_grabber = dll.IC_ReleaseGrabber
dll.release_grabber.argtypes = [C.POINTER(GrabberHandle)]
dll.release_grabber.restype = None

dll.get_property = dll.IC_GetCameraProperty
dll.get_property.argtypes = [GrabberHandle, C.c_uint, C.POINTER(C.c_long)]
dll.get_property.restype = C.c_int

dll.set_property = dll.IC_SetCameraProperty
dll.set_property.argtypes = [GrabberHandle, C.c_uint, C.c_long]
dll.set_property.restype = C.c_int

dll.get_auto_property = dll.IC_GetAutoCameraProperty
dll.get_auto_property.argtypes = [GrabberHandle, C.c_int, C.POINTER(C.c_int)]
dll.get_auto_property.restype = C.c_int

dll.set_auto_property = dll.IC_EnableAutoCameraProperty
dll.set_auto_property.argtypes = [GrabberHandle, C.c_int, C.c_int]
dll.set_auto_property.restype = C.c_int

dll.get_property_range = dll.IC_CameraPropertyGetRange
dll.get_property_range.argtypes = [
    GrabberHandle, C.c_uint, C.POINTER(C.c_long), C.POINTER(C.c_long)]
dll.get_property_range.restype = C.c_int

dll.is_trigger_available = dll.IC_IsTriggerAvailable
dll.is_trigger_available.argtypes = [GrabberHandle]
dll.is_trigger_available.restype = C.c_int

dll.enable_trigger = dll.IC_EnableTrigger
dll.enable_trigger.argtypes = [GrabberHandle, C.c_int]
dll.enable_trigger.restype = C.c_int

dll.software_trigger = dll.IC_SoftwareTrigger
dll.software_trigger.argtypes = [GrabberHandle]
dll.software_trigger.restype = C.c_int

# Initialize the DLL once per module import
assert dll.init(None) == dll.success 

if __name__ == '__main__':
    main()
