#ifndef MONOLED_H
#define MONOLED_H

#include <Arduino.h>
#include <SPI.h>

// For monochrome LEDs, we only need on/off state
typedef bool LEDState;

class MonoLED {
public:
    // Constructor - now takes max LEDs, will be configured in begin()
    MonoLED(int maxLeds, int latchPin, int oePin = -1);

    // Initialize the LED array with specific rows/cols (call in setup())
    void begin(int rows, int cols);

    // Set LED state (true = on, false = off)
    void setPixel(int index, LEDState state);

    // Get LED state
    LEDState getPixel(int index) const;

    // Clear all LEDs
    void clear();

    // Scan a single row for exposure timing / multiplex control
    void scanRow(int row);

    // Set global brightness (0-255, affects all LEDs)
    void setBrightness(uint8_t brightness);

    // Get current brightness
    uint8_t getBrightness() const;

    // Test function - illuminate all LEDs
    void fill(bool state);

    // Get number of LEDs
    int numPixels() const { return _numLeds; }

    // Get rows and columns
    int getRows() const { return _rows; }
    int getCols() const { return _cols; }

    //on off control for all LEDs
    void on();
    void off();

    // Direct access to LED array (for compatibility)
    LEDState* leds;

    //test led
    void testSingleLED();
    void testRow();
    void testColumn();

private:
    int _maxLeds;
    int _numLeds;
    int _rows;
    int _cols;
    int _latchPin;
    int _oePin;
    uint8_t _brightness;

    // Hardware control
    void sendData(uint16_t colData, uint8_t rowData);
    uint8_t rowMask(int row);

    // Convert linear index to row/column
    void indexToRowCol(int index, int& row, int& col);
};

#endif // MONOLED_H