#include <Arduino.h>
#include <SPI.h>
#include <MonoLED.h>

#define PIN_LATCH 15   // GPIO15
#define PIN_OE    4   // GPIO4 (可選)

boolean newData = false;  //stores whether the program is presently receiving new data/input.
const byte numChars = 128; //determines the number of characters for the lists: receivedCharArray,tempStorage, rowLetter, and illuminationCommand
char receivedCharArray[numChars]; // Stores the character input received from the user

/* Components of command received over serial port - row, column and illumination command */ 
char rowLetter[numChars]= {0}; //Stores a single character, that is later used to determine the target row that the user wants to light-up
char plateBarcode[numChars];
int rowNumber;  //used to store the usable-index-number-value obtained with targetIndex, so that targetIndex can be reset to -1 so the convertRowLetterToNumber() keeps working
int columnNumber = 0; //Stores a single number, that is later used to determine the target column that the user wants to light-up
char illuminationCommand[numChars] = {0}; //Stores a single character, that is later used to determine whether the user wants to light-up a row, a column, or a single bulb 

/* Definition of I/O pin count for light guide in 384 well configuration */ 
const int numColumns = 12;  // 96 well 12 Columns
const int numRows = 8;      // 96 well 8 Rows
int pixelNumber;            // Wall number
uint8_t bright = 255;   // LED bright setting, default=255

uint32_t rowExposureTimeMs = 1000;
unsigned long lastRowSwitchMillis = 0;
int currentScanRow = 0;
bool exposureScanActive = false;
bool rowExposureTimeSpecified = false;

// LED control instance
MonoLED leds(96, PIN_LATCH, PIN_OE); // Support up to 96 LEDs

// For compatibility with color commands (ignored for monochrome LEDs)
bool led_color = true;

inline uint8_t clamp8(long v) {
  if (v < 0) return 0;
  if (v > 255) return 255;
  return (uint8_t)v;
}

// ---- ACK/ERR 與十六進位工具 ----
inline void sendAck() { Serial.println(F("<ACK>")); }
inline void sendErr(const __FlashStringHelper* msg) {
  Serial.print(F("<ERR:")); Serial.print(msg); Serial.println(F(">"));
}

// put function declarations here:
void sendData(uint16_t colData, uint8_t rowData);
uint8_t rowMask(int row);
void testSingleLED();
int hexNibble(char c);
bool hexToBytes(const char* hex, uint8_t* out, size_t out_len);
void clearDisplay();
bool commandSupportsRowExposure(const char* cmd);
void startRowExposure();
void illuminateColumn(int column);
void illuminateRow(int row);
void illuminateWell(int c, int r);
void clearRow(int row);
void clearColumn(int column);
void updateDisplay();
void illuminationTest();
void setBright(void);
bool applyMaskHex(const char* maskHex);
void restart(uint32_t wait_ms);
bool isValidColumn(int column);
bool isValidRowIndex(int rowIndex);
bool isValidWell(int column, int rowIndex);
int convertRowLetterToNumber(const char* rowLetterReceived);
void recvWithStartEndMarkers();
void parseData();
void displayParsedCommand();
bool parseIlluminationCommand(const char* cmd);

void setup() {
  // put your setup code here, to run once:
  leds.begin(numRows, numColumns); // Initialize LED matrix
  leds.setBrightness(bright); // Set initial brightness

  Serial.begin(500000);
  /* Print instructions to serial port; useful for debugging or reminding users what the command format is */   
  Serial.printf_P(PSTR("This device has %uX%u=%u LED\n"), numColumns, numRows, numColumns * numRows);
  Serial.println(F("Enter data the following format: <A,1,S,Barcode>"));
  Serial.println(F("First parameter is row letter, second parameter is column, third parameter is illumination command."));
  Serial.println(F("Extended format: <A,1,S,Barcode,255,0,0,50>"));
  Serial.println(F("1 is row letter, 2 is column, 3 is illumination command, 4,5,6 is RGB color, 7 is Bright."));
  Serial.println(F("Valid row and columns are plate density dependent."));
  Serial.println(F("Valid illumination commands are: S - illuminate single well, R - illuminate entire row, C - illuminate entire column."));  
  Serial.println();

  testSingleLED();
  clearDisplay();
}

void loop() {
  // put your main code here, to run repeatedly:
  recvWithStartEndMarkers();
  if (newData == true) {
    parseData();
    displayParsedCommand();
    rowNumber = convertRowLetterToNumber(rowLetter);

    bool ok = parseIlluminationCommand(illuminationCommand);
    if (ok) {
      if (commandSupportsRowExposure(illuminationCommand)) {
        startRowExposure();
      } else {
        exposureScanActive = false;
      }
      sendAck();
    }
    else sendErr(F("BAD_CMD_OR_MASK"));

    newData = false;
  }

  if (exposureScanActive) {
    unsigned long now = millis();
    if (now - lastRowSwitchMillis >= rowExposureTimeMs) {
      lastRowSwitchMillis = now;  // Use current time to avoid drift
      currentScanRow++;
      if (currentScanRow >= numRows) {
        // Scan complete, stop exposure and clear display
        exposureScanActive = false;
        leds.clear();
        leds.show();
        Serial.println(F("Row exposure complete"));
      } else {
        leds.scanRow(currentScanRow);
        Serial.printf_P(PSTR("Row %d\n"), currentScanRow);
      }
    }
  }
}

// put function definitions here:
void sendData(uint16_t colData, uint8_t rowData)
{
  digitalWrite(PIN_LATCH, LOW); // 先送 TLC59283（會被推到後面）
  SPI.transfer16(colData); // 再送 74HC595（會留在最前面）
  SPI.transfer(rowData);
  digitalWrite(PIN_LATCH, HIGH);
}

uint8_t rowMask(int row)
{
  return ~(1 << row); // active LOW
}

void testSingleLED()
{
  for(int r = 0; r < 8; r++)
  {
    for(int c = 0; c < 12; c++)
    {
      uint16_t col = (1 << c);
      sendData(col, rowMask(r));
      delay(50);
    }
  }
}

int hexNibble(char c) {
  if ('0'<=c && c<='9') return c-'0';
  if ('a'<=c && c<='f') return c-'a'+10;
  if ('A'<=c && c<='F') return c-'A'+10;
  return -1;
}

bool hexToBytes(const char* hex, uint8_t* out, size_t out_len) {
  // 兩字元一個 byte，長度需剛好 out_len*2
  size_t n = strlen(hex);
  if (n != out_len*2) return false;
  for (size_t i=0;i<out_len;i++) {
    int hi = hexNibble(hex[2*i]);
    int lo = hexNibble(hex[2*i+1]);
    if (hi<0 || lo<0) return false;
    out[i] = (uint8_t)((hi<<4) | lo);
  }
  return true;
}
/* Turns off all LEDs */
void clearDisplay(){
  leds.clear();
  leds.show();
  Serial.println(F("Display cleared."));
} 

/* Turns on all LEDs for a given column */
void illuminateColumn(int column){
  if (!isValidColumn(column)) {
    Serial.printf_P(PSTR("Column: %u over range!\n"), column);
    return;
  }
  Serial.print(F("Column:"));
  Serial.println(column);
  column=column-1;
  for(int row=0;row<numRows;row++) {
    leds.setPixel(row*numColumns+column, true);
    //Serial.println(row*numColumns+column);
  }
  leds.show();
}

/* Turns on all LEDs for a given row */
void illuminateRow(int row){
  if (!isValidRowIndex(row)) {
    Serial.printf_P(PSTR("Row: %c over range!\n"), row+1+'A');
    return;
  }
  Serial.print(F("Row:"));
  Serial.println(row);
  for (int column=0;column<numColumns;column++){
    leds.setPixel(numColumns*row+column, true);
    //Serial.println(numColumns*row+column);
  }
  leds.show();
}

/* Turns on an individual LED for a given row and column */
void illuminateWell(int c, int r){
  if (!isValidWell(c,r)){
    Serial.printf_P(PSTR("Pixel #: %c,%u over range!\n"), r+'A', c);
  }else{
    pixelNumber = (r)*numColumns+(c-1);
    Serial.print(F("Pixel #:"));
    Serial.println(pixelNumber);
    leds.setPixel(pixelNumber, true);
    leds.show();
  }
}

/* Turns off all LEDs for a given row */
void clearRow(int row){
  if (!isValidRowIndex(row)) {
    Serial.printf_P(PSTR("Row: %c over range!\n"), row+1+'A');
    return;
  }
  Serial.print(F("Clearing row:"));
  Serial.println(row);
  for(int column=0;column<numColumns;column++) {
    leds.setPixel(numColumns*row+column, false);
    //Serial.println(24*row+column);
  }
  leds.show();
}

/* Turns off all LEDs for a given column */
void clearColumn(int column){
  if (!isValidColumn(column)) {
    Serial.printf_P(PSTR("Column: %u over range!\n"), column);
    return;
  }
  Serial.print(F("Clearing column:"));
  Serial.println(column);
  column=column-1;
  for(int row=0;row<numRows;row++) {
    leds.setPixel(row*numColumns+column, false);
    //Serial.println(row*24+column);
  }
  leds.show();
}

/* Command for updating the display */
void updateDisplay() {
  Serial.println("LED Updated");
  leds.show();
}

/* Function to to illuminate one row at a time, useful to run at startup to identify dead LEDs */
void illuminationTest() {
  uint8_t old_bright = leds.getBrightness();
  leds.clear();
  leds.show();
  delay(50);
  Serial.println(F("ALL LED test start!!"));
  leds.setBrightness(min<uint8_t>(old_bright ? old_bright : 32, 32));
  leds.clear();
  leds.show();

  // Test each row
  for (int r = 0; r < numRows; r++) {
    for (int c = 0; c < numColumns; c++) {
      leds.setPixel(r * numColumns + c, true);
    }
    leds.show();
    delay(100);
    leds.clear();
  }

  // Test all LEDs on
  leds.fill(true);
  leds.show();
  delay(800);
  leds.setBrightness(old_bright);
  leds.clear();
  leds.show();
  Serial.println(F("ALL LED off!!"));
}

/* Set LED Bright */
void setBright(void){
  Serial.printf_P(PSTR("Brightness set to %u\n"), bright);
  leds.setBrightness(bright);
  leds.show();
}

// 依 96-bit 遮罩一次設定 LED（LSB-first, row-major：bit0=A01, ... bit95=H12）
bool applyMaskHex(const char* maskHex) {
  if (!maskHex) return false;
  const int total = numRows * numColumns; // 96
  const int BYTES = (total + 7) / 8;      // 12
  uint8_t mask[BYTES];
  if (!hexToBytes(maskHex, mask, BYTES)) return false;

  // 這裡的策略：未選取者設為false，選取者設為true
  leds.clear();
  for (int idx = 0; idx < total; ++idx) {
    int byte_i = idx >> 3;        // /8
    int bit_i  = idx & 7;         // %8, LSB-first
    if (mask[byte_i] & (1 << bit_i)) {
      leds.setPixel(idx, true);
    }
  }
  leds.show();
  return true;
}

/* Software restart */
void restart(uint32_t wait_ms = 100) {
  leds.clear();
  leds.show();
  Serial.println(F("Restarting..."));
  Serial.flush();           // 盡量把序列訊息送出去
  delay(wait_ms);           // 給 USB/UART 一點時間
  ESP.restart();            // 軟重啟
  while (true) { delay(1); } // 理論上不會執行到這；保險阻塞
}

/* Column range check */
bool isValidColumn(int column) {
  return column >= 1 && column <= numColumns;
}

/* Row range check */
bool isValidRowIndex(int rowIndex) {
  return rowIndex >= 0 && rowIndex < numRows;
}

/* Well range check */
bool isValidWell(int column, int rowIndex) {
  return isValidColumn(column) && isValidRowIndex(rowIndex);
}

/* Convert the row letter to a number value */ 
int convertRowLetterToNumber(const char* rowLetterReceived){
  /* The character A is represented by the integer value 65, subtract that and you have the integer value of the row number */ 
  if (!rowLetterReceived || rowLetterReceived[0] == '\0') return -1;
  char ch = rowLetterReceived[0];
  if (ch < 'A' || ch > 'Z') return -1;
  //int idx = ch - 'A';
  //return (idx < numRows) ? idx : -1;
  return ch - 'A';
}

/* Receive incoming serial data and store in receivedCharArray array */ 
void recvWithStartEndMarkers() {
  static boolean recvInProgress = false;
  static byte indexListCounter = 0;
  char startMarker = '<';
  char endMarker = '>';
  char receivedCharacter;
  while (Serial.available() > 0 && newData == false) {
    receivedCharacter = Serial.read();
    if (recvInProgress == true) {
      if (receivedCharacter != endMarker) {
        receivedCharArray[indexListCounter] = receivedCharacter;
        indexListCounter++;
        if (indexListCounter >= numChars) {
          indexListCounter = numChars - 1;
        }
      }
      else {
        receivedCharArray[indexListCounter] = '\0'; // terminate the string
        recvInProgress = false;
        indexListCounter = 0;
        newData = true;
      }
    }
    else if (receivedCharacter == startMarker) {
      recvInProgress = true;
    }
  }
}

/* Parse incoming serial data */ 
/*
void parseData() {      
    char * strtokIndx; // this is used by strtok() as an index
    strtokIndx = strtok(receivedCharArray,",");      // get the first part - the string
    strcpy(rowLetter, strtokIndx); // copy it to rowLetter       
    strtokIndx = strtok(NULL, ","); // this continues where the previous call left off
    columnNumber = atoi(strtokIndx);// convert this part to an integer    
    strtokIndx = strtok(NULL,",");      // get the first part - the string    
    strcpy(illuminationCommand, strtokIndx); // copy it to illuminationCommand
    strtokIndx = strtok(NULL,",");      // get the plate barcode
    strcpy(plateBarcode, strtokIndx); // copy it to illuminationCommand
} 
*/
void parseData() {      
  char* tokens[12];
  int tokenCount = 0;
  char* strtokIndx = strtok(receivedCharArray, ",");
  while (strtokIndx && tokenCount < 12) {
    tokens[tokenCount++] = strtokIndx;
    strtokIndx = strtok(NULL, ",");
  }

  long r = -1, g = -1, b = -1, bri = -1;
  rowExposureTimeSpecified = false;

  if (tokenCount > 0) strcpy(rowLetter, tokens[0]); else rowLetter[0] = '\0';
  if (tokenCount > 1) columnNumber = atoi(tokens[1]); else columnNumber = 0;
  if (tokenCount > 2) strcpy(illuminationCommand, tokens[2]); else illuminationCommand[0] = '\0';
  if (tokenCount > 3) strcpy(plateBarcode, tokens[3]); else plateBarcode[0] = '\0';

  // 根據 token 數量推測哪個是時間參數
  // 格式1: <A,1,C,barcode,timeMs> (5 tokens)
  // 格式2: <A,1,C,barcode,R,G,B> (7 tokens) - no time
  // 格式3: <A,1,C,barcode,R,G,B,timeMs> (8 tokens) - time at end
  if (tokenCount == 5 && commandSupportsRowExposure(illuminationCommand)) {
    long tmpTime = strtol(tokens[4], NULL, 10);
    if (tmpTime > 0 && tmpTime <= 100000) { // 時間範圍: 0-100s
      rowExposureTimeMs = (uint32_t)tmpTime;
      rowExposureTimeSpecified = true;
    } else {
      // 可能是 RGB 的 R 值，不是時間
      r = tmpTime;
    }
  } else if (tokenCount >= 8 && commandSupportsRowExposure(illuminationCommand)) {
    // 最後一個參數可能是時間
    long tmpTime = strtol(tokens[tokenCount - 1], NULL, 10);
    if (tmpTime > 0 && tmpTime <= 100000) {
      rowExposureTimeMs = (uint32_t)tmpTime;
      rowExposureTimeSpecified = true;
    } else {
      bri = tmpTime;
    }
  }

  // 解析 RGB（如果有）
  if (tokenCount > 4) {
    if (r < 0) r = strtol(tokens[4], NULL, 10);
  }
  if (tokenCount > 5) g = strtol(tokens[5], NULL, 10);
  if (tokenCount > 6) b = strtol(tokens[6], NULL, 10);
  if (tokenCount > 7) bri = strtol(tokens[7], NULL, 10);

  // 有提供 R/G/B 就更新顏色（不限制指令）- 對於單色LED，任何非零顏色都設為true
  if (r >= 0 && g >= 0 && b >= 0) {
    led_color = (r > 0 || g > 0 || b > 0);
    Serial.printf_P(PSTR("Color set to %s\n"), led_color ? "ON" : "OFF");
  }
  // 只有在 L 指令時才允許修改亮度
  if (strcmp(illuminationCommand, "L") == 0 && bri >= 0) {
    bright = clamp8(bri);
  }
}

/* Displays the parsed information to the serial terminal; useful for debugging communication issues */ 
void displayParsedCommand() {
  Serial.printf_P(PSTR("Command:%s, Address:%s%u, "), illuminationCommand, rowLetter, columnNumber);
  /*display.clearDisplay();
  display.setCursor(0,0);
  display.setTextSize(1);
  display.print(F("Barcode:"));
  display.setCursor(0,16);
  display.setTextSize(1);
  display.print(String(plateBarcode));
  display.display();*/
}

/* Determine which illumination command has been received and call the corresponding illumination function */ 
bool parseIlluminationCommand(const char* cmd){
  if (!cmd) return false;

  if (strcmp(cmd, "X")   == 0) { clearDisplay();                    return true; }
  else if (strcmp(cmd, "C")   == 0) { illuminateColumn(columnNumber);   return true; }
  else if (strcmp(cmd, "R")   == 0) { illuminateRow(rowNumber);         return true; }
  else if (strcmp(cmd, "S")   == 0) { illuminateWell(columnNumber, rowNumber); return true; }
  else if (strcmp(cmd, "CR")  == 0) { clearRow(rowNumber);              return true; }
  else if (strcmp(cmd, "CC")  == 0) { clearColumn(columnNumber);        return true; }
  else if (strcmp(cmd, "U")   == 0) { updateDisplay();                  return true; }
  else if (strcmp(cmd, "T")   == 0) { illuminationTest();               return true; }
  else if (strcmp(cmd, "L")   == 0) { setBright();                      return true; }
  else if (strcmp(cmd, "RST") == 0) { sendAck(); restart(500);          return true; }
  else if (strcmp(cmd, "M")   == 0) {
    // 這裡沿用 plateBarcode 當 24Hex 遮罩承載（parseData 第 4 個欄位）
    if (applyMaskHex(plateBarcode)) return true;
    else return false;
  }
  else {
    Serial.println(F("ERROR Appropriate value not received."));
    return false;
  }
}

bool commandSupportsRowExposure(const char* cmd) {
  return cmd && (
      strcmp(cmd, "C") == 0 ||
      strcmp(cmd, "R") == 0 ||
      strcmp(cmd, "S") == 0 ||
      strcmp(cmd, "M") == 0);
}

void startRowExposure() {
  currentScanRow = 0;
  lastRowSwitchMillis = millis();
  exposureScanActive = true;
  // First display the first row
  leds.scanRow(currentScanRow);
  Serial.printf_P(PSTR("Row exposure start: 0, time=%ums\n"), rowExposureTimeMs);
}
