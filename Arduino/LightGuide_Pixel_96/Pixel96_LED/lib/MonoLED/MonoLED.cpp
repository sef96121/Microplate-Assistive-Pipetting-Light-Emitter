#include "MonoLED.h"

MonoLED::MonoLED(int maxLeds, int latchPin, int oePin) : _maxLeds(maxLeds), _numLeds(0), _rows(0), _cols(0), _latchPin(latchPin), _oePin(oePin), _brightness(255) {
    leds = new LEDState[maxLeds];
    clear();
}

void MonoLED::begin(int rows, int cols) {
    _rows = rows;
    _cols = cols;
    _numLeds = rows * cols;
    if (_numLeds > _maxLeds){
        // Error: too many LEDs requested
        _numLeds = _maxLeds;
    }
    pinMode(_latchPin, OUTPUT);
    if (_oePin >= 0){
        pinMode(_oePin, OUTPUT);
        digitalWrite(_oePin, LOW); // Enable output (active LOW)
    }
    SPI.begin();
    SPI.setFrequency(8000000); // 8MHz SPI clock
}

void MonoLED::setPixel(int index, LEDState state) {
    if (index >= 0 && index < _numLeds) {
        leds[index] = state;
    }
}

LEDState MonoLED::getPixel(int index) const {
    if (index >= 0 && index < _numLeds) {
        return leds[index];
    }
    return false;
}

void MonoLED::clear(){
    for (int i = 0; i < _maxLeds; i++) {
        leds[i] = false;
    }
}

void MonoLED::scanRow(int row) {
    if (row < 0 || row >= _rows)return;
    uint16_t colData = 0;
    for (int col = 0; col < _cols && col < 16; col++) {
        int index = row * _cols + col;
        if (index < _numLeds && leds[index]) {
            colData |= (1 << col);
        }
    }
    sendData(colData, rowMask(row));
    // delayMicroseconds(200);  // Ensure data is latched properly
}

void MonoLED::setBrightness(uint8_t brightness) {
    _brightness = brightness;
    // For monochrome LEDs with TLC59283 constant current,
    // brightness control might need external PWM on OE pin
    if (_oePin >= 0) {
        // Simple PWM implementation for brightness
        // This is a basic implementation - may need refinement
        analogWrite(_oePin, 255 - brightness);
    }
}

uint8_t MonoLED::getBrightness() const {
    return _brightness;
}

void MonoLED::fill(bool state) {
    for (int i = 0; i < _numLeds; i++) {
        leds[i] = state;
    }
}

void MonoLED::sendData(uint16_t colData, uint8_t rowData) {
    digitalWrite(_latchPin, LOW);
    SPI.transfer16(colData); // TLC59283 data (16-bit)
    SPI.transfer(rowData);   // 74HC595 data (8-bit)
    digitalWrite(_latchPin, HIGH);
}

uint8_t MonoLED::rowMask(int row) {
    return ~(1 << row); // Active LOW
}

void MonoLED::indexToRowCol(int index, int &row, int &col) {
    row = index / _cols;
    col = index % _cols;
}

void MonoLED::on() {
    if (_oePin >= 0) {
        // Simple PWM implementation for brightness
        // This is a basic implementation - may need refinement
        analogWrite(_oePin, 255 - _brightness);
    }
}

void MonoLED::off() {
    sendData(0000, 0xFF);     // Turn off all LEDs
    if (_oePin >= 0) {
        analogWrite(_oePin, 255); // Disable output (active LOW)
    }
}

void MonoLED::testSingleLED() {
    for (int r = 0; r < _rows; r++) {
        for (int c = 0; c < _cols; c++) {
            uint16_t col = (1 << c);
            uint8_t row = rowMask(r);
            sendData(col, row);
            delay(50);
        }
    }
}

void MonoLED::testRow() {
  uint16_t col = 0x0FFF; // 12 顆全亮
  for(int r = 0; r < _rows; r++) {
    sendData(col, rowMask(r));
    delay(300);
  }
}

void MonoLED::testColumn() {
  for(int c = 0; c < _cols; c++) {
    uint16_t col = (1 << c);
    for(int r = 0; r < _rows; r++) {
      sendData(col, rowMask(r));
      delay(50);
    }
  }
}