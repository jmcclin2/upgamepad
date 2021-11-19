# Micropython imports
from micropython import const
import framebuf

import gc

# Machine specific imports
from machine import Pin
from machine import SPI
from machine import I2C

# External module imports
from upssd1327.ssd1327 import SSD1327_SPI
from up2axisjoystick.two_axis_analog_joystick import TwoAxisAnalogJoystick
from up2axisjoystick.two_axis_analog_joystick import SS_CENTERED, SS_LEFT_MIN, SS_LEFT_MID, SS_LEFT_MAX, SS_RIGHT_MIN, SS_RIGHT_MID, SS_RIGHT_MAX, SS_UP_MIN, SS_UP_MID, SS_UP_MAX, SS_DOWN_MIN, SS_DOWN_MID, SS_DOWN_MAX, X_VALUE_LIST_INDEX, Y_VALUE_LIST_INDEX
from updebouncein.debounced_input import DebouncedInput

import logo_data

# Raspberry Pico Abstraction
_SSD1327_SPI_BUS         = const(0)
_SSD1327_SPI_SCK_PIN     = const(6)
_SSD1327_SPI_MOSI_PIN    = const(7)
_SSD1327_DC_PIN          = const(8)
_SSD1327_RES_PIN         = const(9)
_SSD1327_CS_PIN          = const(5)

_DISPLAY_HEIGHT_PIXELS   = const(128)
_DISPLAY_WIDTH_PIXELS    = const(128)

_JOYSTICK_X_ATOD_PIN     = const(26)
_JOYSTICK_Y_ATOD_PIN     = const(27)

_BUTTON_A_PIN            = const(2)
_BUTTON_B_PIN            = const(3)
_BUTTON_JOY_PIN          = const(0)
_BUTTON_O_PIN            = const(1)
_BUTTON_L_SHOULDER_PIN   = const(2)
_BUTTON_R_SHOULDER_PIN   = const(2)

# Internal State
_GAME_STATE_INT_MENU     = const(0)  # Internal menu active
_GAME_STATE_EXT_RUN      = const(1)  # External game running

# External Joystick Mode
JOYSTICK_MODE_RAW        = const(0x01)
JOYSTICK_MODE_STATE      = const(0x02)

class Gamepad:
    
    # Joystick Callback
    def _joystick_cb(self, is_raw, val):
        
        # If external game is running return desired joystick values to user
        if (self.joystick_cb and self.game_state == _GAME_STATE_EXT_RUN):
            self.joystick_cb(self.joystick_mode, val)
        
        elif (self.game_state == _GAME_STATE_INT_MENU):
            # If resutls are raw, convert to state first
            if (is_raw):
                state = self.joystick.ConvertRawToState(val)
                val = state
            
            # Adjust pixel x coordinate based on joystick deflection
            self.cur_x += self.x_rate_lut[val[X_VALUE_LIST_INDEX]]
                    
            # Bounds check
            if (self.cur_x < 0):
                self.cur_x = 0
            elif (self.cur_x > _DISPLAY_WIDTH_PIXELS-1):
                self.cur_x = _DISPLAY_WIDTH_PIXELS-1
                
            # Adjust pixel y coordinate based on joystick deflection
            # Note: for display, positive change is down, negative is up
            self.cur_y += self.y_rate_lut[val[Y_VALUE_LIST_INDEX]]

            # Bounds check
            if (self.cur_y < 0):
                self.cur_y = 0
            elif (self.cur_y > _DISPLAY_HEIGHT_PIXELS-1):
                self.cur_y = _DISPLAY_HEIGHT_PIXELS-1
                
            #print("_joystick_cb x:" + str(self.cur_x) + " y:" + str(self.cur_y))
    
    # Button callbacks
    def a_button_cb(self, pin, state, duration):
        if (self.button_cb["A"] and self.game_state == _GAME_STATE_EXT_RUN):
            self.button_cb["A"](pin, state, duration)
        else:
            print("A Button:" + str(state))
    
    def b_button_cb(self, pin, state, duration):
        if (self.button_cb["B"] and self.game_state == _GAME_STATE_EXT_RUN):
            self.button_cb["B"](pin, state, duration)
        else:
            print("B Button:" + str(state))
        
    def joy_button_cb(self, pin, state, duration):
        if (self.button_cb["J"] and self.game_state == _GAME_STATE_EXT_RUN):
            self.button_cb["J"](pin, state, duration)
        else:
            print("JOY Button:" + str(state))
        
    def opt_button_cb(self, pin, state, duration):
        if (self.button_cb["O"] and self.game_state == _GAME_STATE_EXT_RUN):
            self.button_cb["O"](pin, state, duration)
        else:
            print("OPTION Button:" + str(state))
    
    def lshldr_button_cb(self, pin, state, duration):
        if (self.button_cb["LS"] and self.game_state == _GAME_STATE_EXT_RUN):
            self.button_cb["LS"](pin, state, duration)
        else:
            print("LS Button:" + str(state))
    
    def rshldr_button_cb(self, pin, state, duration):
        if (self.button_cb["RS"] and self.game_state == _GAME_STATE_EXT_RUN):
            self.button_cb["RS"](pin, state, duration)
        else:
            print("RS Button:" + str(state))
    
    """Micropython Gamepad Class"""
    def __init__(self, button_cb={"A":None, "B":None, "J":None, "O":None, "LS":None, "RS":None}, joystick_cb=None, joystick_mode=JOYSTICK_MODE_STATE):
        
        # Joystick co-ordiantes
        self.cur_x = 0;
        self.cur_y = 0;
        
        # Joystick user callback and requested mode
        self.joystick_cb = joystick_cb
        self.joystick_mode = joystick_mode
        
        # Joystick movement rate lookup
        self.x_rate_lut = { SS_CENTERED:0, SS_LEFT_MIN:-1, SS_LEFT_MID:-3, SS_LEFT_MAX:-6, SS_RIGHT_MIN:1, SS_RIGHT_MID:3, SS_RIGHT_MAX:6 }
        self.y_rate_lut = { SS_CENTERED:0, SS_UP_MIN:-1, SS_UP_MID:-3, SS_UP_MAX:-6, SS_DOWN_MIN:1, SS_DOWN_MID:3, SS_DOWN_MAX:6 }
        
        # Button callbacks
        self.button_cb = button_cb
        
        # Gamestate
        self.game_state = _GAME_STATE_EXT_RUN
        
        # Setup SPI bus used for display
        ssd1327_spi = SPI(_SSD1327_SPI_BUS, sck=Pin(_SSD1327_SPI_SCK_PIN), mosi=Pin(_SSD1327_SPI_MOSI_PIN))

        # Initialize display
        self.ssd1327 = SSD1327_SPI(_DISPLAY_WIDTH_PIXELS, _DISPLAY_HEIGHT_PIXELS, ssd1327_spi, Pin(_SSD1327_DC_PIN), Pin(_SSD1327_RES_PIN), Pin(_SSD1327_CS_PIN))

        # Show splash logo
        a = bytearray(logo_data.data())
        fbuf = framebuf.FrameBuffer(a, _DISPLAY_WIDTH_PIXELS, _DISPLAY_HEIGHT_PIXELS, framebuf.GS4_HMSB)
        self.show(fbuf)
        
        # Initialize joystick
        self.joystick = TwoAxisAnalogJoystick(_JOYSTICK_X_ATOD_PIN, _JOYSTICK_Y_ATOD_PIN, polling_ms=1000, callback=self._joystick_cb, deadzone=0x2000)
        self.joystick.StartPolling()
        
        self.a_button = DebouncedInput(_BUTTON_A_PIN, self.a_button_cb, pin_pull=Pin.PULL_UP, pin_logic_pressed=False, debounce_ms=50)
        self.b_button = DebouncedInput(_BUTTON_B_PIN, self.b_button_cb, pin_pull=Pin.PULL_UP, pin_logic_pressed=False, debounce_ms=50)
        self.joy_button = DebouncedInput(_BUTTON_JOY_PIN, self.joy_button_cb, pin_pull=Pin.PULL_UP, pin_logic_pressed=False, debounce_ms=50)
        self.option_button = DebouncedInput(_BUTTON_O_PIN, self.opt_button_cb, pin_pull=Pin.PULL_UP, pin_logic_pressed=False, debounce_ms=50)
        #self.left_shoulder = DebouncedInput(_BUTTON_L_SHOULDER_PIN, self.lshldr_button_cb, pin_pull=Pin.PULL_UP, pin_logic_pressed=False, debounce_ms=50)
        #self.right_shoulder = DebouncedInput(_BUTTON_R_SHOULDER_PIN, self.rshldr_button_cb, pin_pull=Pin.PULL_UP, pin_logic_pressed=False, debounce_ms=50)
            
    def show(self, framebuf):        
        self.ssd1327.fill(0)
        self.ssd1327.blit(framebuf, 0, 0, 0)
        self.ssd1327.show()
        
    def joystick_state(self):
        return self.joystick.GetCurrentState()
        
    def joystick_raw(self):
        return self.joystick.GetRawCount()
    
    def joystick_reverse_x(self):
        return self.joystick.ReverseX()
    
    def joystick_reverse_y(self):
        return self.joystick.ReverseY()
        
        