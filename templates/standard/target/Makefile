###############################################################################
#   Copyright (c) 2019-2021 ams AG
#   Copyright (c) 2022 Thomas Winkler <thomas.winkler@gmail.com>
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
###############################################################################

# This Makefile was developed and tested with GNU make 4.1.

.PHONY: default all clean

# Directory where the Makefile is located
MAKEFILEDIR := $(dir $(realpath $(lastword $(MAKEFILE_LIST))))

# Remove trailing slash, if any.
MAKEFILEDIR := $(patsubst %/,%,$(MAKEFILEDIR))

# OS detection; host OS is stored in the HOSTOS variable as Windows_NT or Linux.
ifeq ($(OS),Windows_NT)
  HOSTOS := $(OS)
else
  HOSTOS := $(shell uname -s)
  ifneq ($(HOSTOS),Linux)
    $(error Host OS could not be detected or is not supported!)
  endif
endif
$(info detected host OS: $(HOSTOS))

# Output folder for binary files
OUTDIR_BASE = build

# Source folder
SRCDIR = $(MAKEFILEDIR)


# Compiler binaries
CC = arm-none-eabi-gcc
AS = arm-none-eabi-as
LD = arm-none-eabi-gcc
AR = arm-none-eabi-ar
OBJCOPY = arm-none-eabi-objcopy
OBJDUMP = arm-none-eabi-objdump

# Check if compiler can be executed; otherwise exit with an error message
CCCHECK := $(shell $(CC) --version 2>&1 > /dev/null; echo $$?)
ifneq ($(CCCHECK),0)
  $(warning Compiler $(CC) not found. Ensure that it is in the PATH!)
endif

# DOTT test framework paths
DOTTDIR=$(MAKEFILEDIR)/../../..
DOTTDIR_SUBST=dott

# Flags passed to the assembler
ASFLAGS  = -mcpu=cortex-m0 -g -mthumb

# Flags passed to the C compiler
CFLAGS  = -xc -std=c99 -mcpu=cortex-m0 -mthumb -mlittle-endian
CFLAGS += -flto -funsigned-char -fshort-enums -fshort-wchar
CFLAGS += -MD -gdwarf-4 -ffunction-sections
CFLAGS += -Wall

# Include directories
INCDIRS  = -I$(MAKEFILEDIR)/Drivers/CMSIS/Include
INCDIRS += -I$(MAKEFILEDIR)/Drivers/CMSIS/Device/ST/STM32F0xx/Include
INCDIRS += -I$(DOTTDIR)/target
CFLAGS  += $(INCDIRS)

# CFLAGS for STM32 HAL
CFLAGS += -DSTM32F072xB
CFLAGS += -D__weak="__attribute__((weak))"
CFLAGS += -D__packed="__attribute__((packed))"

# Flags passed to the linker
LDFLAGS  = -nostartfiles --specs=nano.specs -Wl,--discard-none
LDFLAGS += -mcpu=cortex-m0 -mthumb -mlittle-endian

# C source files to be built
SRC = $(DOTTDIR)/target/testhelpers.c \
      system_stm32f0xx.c \
      main.c

# Assembly source files to be built
ASMSRC = Drivers/CMSIS/Device/ST/STM32F0xx/Source/Templates/gcc/startup_stm32f072xb.s

# Create list of object files and add object directory prefix
OBJS  = $(ASMSRC:%.s=%.o)
OBJS += $(subst $(DOTTDIR),$(DOTTDIR_SUBST),$(SRC:%.c=%.o))

# Create list of dependency files (generated via -MD) and include them
DEPS = $(OBJS:%.o=%.d)
-include $(DEPS)

# The default (first) target to build is 'all'
all: dott_template_std dott_template_std_noopt


# Build rule template for a single object file from an assembly file
define AS_OUT_SUBDIR_RULE
$1/%.o: $(SRCDIR)/%.s
	$$(info [AS] $$< -> $$@)
	@mkdir -p $$(dir $$@)
	$(AS) $$(ASFLAGS) -o $$@ $$<
endef


# Build rule template for a single object file from a C source file
define CC_OUT_SUBDIR_RULE
$1/%.o: $(SRCDIR)/%.c
	$$(info [CC] $$< -> $$@)
	@mkdir -p $$(dir $$@)
	$(CC) -c $$(CFLAGS) -o $$@ $$<

$1/$(DOTTDIR_SUBST)/%.o: $(DOTTDIR)/%.c
	$$(info [CC] $$< -> $$@)
	@mkdir -p $$(dir $$@)
	$(CC) -c $$(CFLAGS) -o $$@ $$<
endef

# Remove all build artifacts
clean:
	$(info [RM] $(OUTDIR_BASE))
	@rm -rf $(OUTDIR_BASE)

# Generic target to link all objects into final ELF binary and create final firmware image
dott_%:
	$(eval MAPFILE = $(OUTDIR)/$@.map)
	$(eval BINFILE = $(OUTDIR)/$@.bin)
	$(eval ELFFILE = $(OUTDIR)/$@.elf)
	$(eval DISASFILE = $(OUTDIR)/$@.lst)
	$(info [LD] $(firstword $?))
	$(foreach OBJ,$(wordlist 2, $(words $?), $?), $(info $(DUMMY)     $(OBJ)))
	$(info $(DUMMY)     -> $(ELFFILE) (ELF Binary))
	$(LD) $(LDFLAGS) -Wl,-Map=$(MAPFILE) $? -o $(ELFFILE)
	@$(OBJDUMP) -D -S $(ELFFILE) > $(DISASFILE)
	@$(OBJCOPY) -O binary $(ELFFILE) $(BINFILE)
	@$(OBJCOPY) --input-target=binary --output-target=elf32-little --change-addresses=$(LMAADDR) \
	            --rename-section .data=.rodata,alloc,load,readonly,data,contents $(BINFILE) $(BINFILE).elf
	@$(OBJDUMP) -h $(BINFILE).elf

# Output directories (below OUTDIR_BASE)
OUTDIR_TMP = $(OUTDIR_BASE)/dott_template_std
OUTDIR_TMP_NOOPT = $(OUTDIR_BASE)/dott_template_std_noopt
OUTDIRS = $(OUTDIR_TMP) $(OUTDIR_TMP_NOOPT)

# Instantiate object target templates based on outdir list
$(foreach DIR, $(OUTDIRS), $(eval $(call CC_OUT_SUBDIR_RULE, $(DIR))))
$(foreach DIR, $(OUTDIRS), $(eval $(call AS_OUT_SUBDIR_RULE, $(DIR))))


# --- Firmware targets ---

dott_template_std: LMAADDR = 0x00000000
dott_template_std: LDFLAGS += -T stm32_gcc_flash.ld
dott_template_std: CFLAGS += -O3
dott_template_std: OUTDIR = $(OUTDIR_TMP)
dott_template_std: $(addprefix $(OUTDIR_TMP)/, \
                         $(OBJS) \
                   )

dott_template_std_noopt: LMAADDR = 0x00000000
dott_template_std_noopt: LDFLAGS += -T stm32_gcc_flash.ld
dott_template_std_noopt: CFLAGS += -O0
dott_template_std_noopt: OUTDIR = $(OUTDIR_TMP_NOOPT)
dott_template_std_noopt: $(addprefix $(OUTDIR_TMP_NOOPT)/, \
                         $(OBJS) \
                       )
